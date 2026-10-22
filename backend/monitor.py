import asyncio
import logging
import time

from . import probes

logger = logging.getLogger(__name__)


class Monitor:
    def __init__(self, store):
        self.store = store
        self.lock = asyncio.Lock()
        self.task = None
        self.last_cycle = None
        self.error = None

    async def start(self):
        self.task = asyncio.create_task(self.run(), name="netpulse-collector")

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def run(self):
        while True:
            started = time.monotonic()
            try:
                async with self.lock:
                    config = self.store.config()
                    settings = config['settings']
                    semaphore = asyncio.Semaphore(4)

                    async def measure(target):
                        async with semaphore:
                            try:
                                if target['kind'] == 'ping':
                                    result = await probes.ping(target['address'], settings['ping_count'], settings['timeout_seconds'])
                                elif target['kind'] == 'dns':
                                    result = await probes.dns_probe(target['address'], settings['timeout_seconds'])
                                else:
                                    result = await probes.http_probe(target['address'], settings['timeout_seconds'])
                            except Exception as exc:
                                logger.exception("Falha da sonda %s", target['id'])
                                result = probes.Measurement(None, error=f"Erro de coleta: {type(exc).__name__}")
                            self.store.record(target['id'], result)

                    # A storage failure must cancel and join siblings before releasing the lock.
                    async with asyncio.TaskGroup() as group:
                        for target in config['targets']:
                            if target['enabled']:
                                group.create_task(measure(target))
                    self.store.prune(settings['retention_days'])
                    from .storage import now
                    self.last_cycle = now()
                    self.error = None
                delay = max(0.1, settings['interval_seconds'] - (time.monotonic() - started))
            except Exception as exc:
                logger.exception("Falha no ciclo de monitoramento")
                self.error = str(exc)[:300]
                delay = 5
            await asyncio.sleep(delay)
