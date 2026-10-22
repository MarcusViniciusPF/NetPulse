import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .models import Configuration
from . import __version__
from .monitor import Monitor
from .probes import detect_gateway
from .storage import Store

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')


def create_app(db_path: str | None = None, monitoring: bool = True):
    @asynccontextmanager
    async def lifespan(app):
        path = Path(db_path or os.getenv('NETPULSE_DB', 'data/netpulse.sqlite3'))
        if not path.is_absolute():
            path = ROOT / path
        app.state.store = Store(str(path))
        app.state.gateway = await detect_gateway() if monitoring else None
        app.state.store.seed(app.state.gateway)
        app.state.monitor = Monitor(app.state.store)
        if monitoring:
            await app.state.monitor.start()
        try:
            yield
        finally:
            await app.state.monitor.stop()

    app = FastAPI(title='NetPulse', version=__version__, lifespan=lifespan)
    origins = [origin.strip().rstrip('/') for origin in os.getenv(
        'NETPULSE_CORS', 'http://localhost:5173,http://127.0.0.1:5173').split(',') if origin.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins,
                       allow_methods=['GET', 'PUT'], allow_headers=['Content-Type'])

    @app.get('/health', include_in_schema=False)
    @app.get('/api/health')
    async def health():
        monitor = app.state.monitor
        running = bool(monitor.task and not monitor.task.done())
        return {'status': 'degraded' if monitor.error or not running else 'ok', 'collector_running': running,
                'last_cycle': monitor.last_cycle, 'error': monitor.error, 'gateway': app.state.gateway,
                'mode': 'real'}

    @app.get('/api/config')
    async def config():
        return app.state.store.config()

    @app.put('/api/config')
    async def update_config(config: Configuration):
        # Never change targets halfway through a measurement cycle.
        async with app.state.monitor.lock:
            try:
                app.state.store.save_config(config)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        return app.state.store.config()

    @app.get('/api/dashboard')
    async def dashboard(hours: int = Query(24, ge=1, le=8760), target_id: int | None = Query(None, ge=1)):
        return app.state.store.dashboard(hours, target_id)

    # Built assets share the API origin in production. Unknown API routes must stay 404.
    dist = ROOT / 'frontend/dist'
    if dist.is_dir():
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

        @app.get('/', include_in_schema=False)
        async def index():
            from fastapi.responses import FileResponse
            return FileResponse(dist / 'index.html')

    return app


app = create_app()

if __name__ == '__main__':
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run('backend.main:app', host=os.getenv('NETPULSE_HOST', '127.0.0.1'),
                port=int(os.getenv('NETPULSE_PORT', '8000')), workers=1)
