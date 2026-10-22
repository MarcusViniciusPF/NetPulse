"""Integração local real: Uvicorn, HTTP, ping, SQLite e shutdown."""
import asyncio
import socket

import httpx
import uvicorn

from backend.main import create_app
from backend.models import Configuration, Settings, Target
from backend.storage import Store


async def test_live_service_and_graceful_shutdown(tmp_path):
    # Reserve a loopback socket until Uvicorn takes ownership; no port race.
    sock=socket.socket()
    sock.bind(('127.0.0.1',0))
    port=sock.getsockname()[1]
    path=str(tmp_path/'runtime.sqlite3')
    store=Store(path)
    store.save_config(Configuration(settings=Settings(interval_seconds=5,ping_count=1,timeout_seconds=1),targets=[
        Target(name='Loopback',kind='ping',address='127.0.0.1'),
        Target(name='API local',kind='http',address=f'http://127.0.0.1:{port}/api/health')]))
    app=create_app(path)
    probe_state={'status':200}
    from fastapi.responses import Response

    @app.get('/controlled-probe')
    async def controlled_probe():
        return Response(status_code=probe_state['status'])

    config=store.config()
    config['targets'][1]['address']=f'http://127.0.0.1:{port}/controlled-probe'
    # Recreate the test database before startup; no historical measurements yet.
    with store.connection() as db:
        db.execute('UPDATE targets SET address=? WHERE id=?', (config['targets'][1]['address'],config['targets'][1]['id']))
    server=uvicorn.Server(uvicorn.Config(app,log_level='warning',lifespan='on'))
    task=asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:break
            if task.done():await task
            await asyncio.sleep(.1)
        assert server.started
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}',trust_env=False) as client:
            for _ in range(150):
                data=(await client.get('/api/dashboard')).json()
                if all(t['latest'] for t in data['targets']):break
                await asyncio.sleep(.1)
            assert all(t['latest'] for t in data['targets'])
            assert data['targets'][1]['latest']['success'] == 1
            # ICMP may be blocked by host policy, but must be an actual recorded result.
            assert data['targets'][0]['latest']['timestamp']
            assert (await client.get('/api/health')).json()['collector_running'] is True
            if __import__('pathlib').Path('frontend/dist/index.html').exists():
                assert 'NetPulse' in (await client.get('/')).text
            # Observe a real HTTP outage and recovery through complete collector cycles.
            probe_state['status']=503
            for _ in range(150):
                data=(await client.get('/api/dashboard')).json()
                if any(o['target_id']==data['targets'][1]['id'] and o['recovered_at'] is None for o in data['outages']):break
                await asyncio.sleep(.1)
            target_id=data['targets'][1]['id']
            assert any(o['target_id']==target_id and o['recovered_at'] is None for o in data['outages'])
            assert data['targets'][1]['latest']['error'] == 'HTTP 503'
            probe_state['status']=200
            for _ in range(150):
                data=(await client.get('/api/dashboard')).json()
                if data['targets'][1]['latest']['success']==1:break
                await asyncio.sleep(.1)
            assert data['targets'][1]['latest']['success']==1
            assert any(o['target_id']==target_id and o['end_reason']=='recovered' for o in data['outages'])
    finally:
        server.should_exit=True
        await asyncio.wait_for(task,10)
        sock.close()
    assert app.state.monitor.task.done()
    assert Store(path).dashboard(24)['targets'][1]['latest']['success'] == 1
