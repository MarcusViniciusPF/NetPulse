import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.monitor import Monitor
from backend.probes import Measurement, parse_reply
from backend import probes


def test_health_alias_and_cors_normalization(tmp_path, monkeypatch):
    monkeypatch.setenv('NETPULSE_CORS', ' http://localhost:5173/ , http://127.0.0.1:5173 ')
    with TestClient(create_app(str(tmp_path/'cors.sqlite3'), monitoring=False)) as client:
        assert client.get('/health').json() == client.get('/api/health').json()
        assert client.get('/health').json()['status'] == 'degraded'
        for origin in ['http://localhost:5173', 'http://127.0.0.1:5173']:
            response=client.options('/api/config', headers={'Origin':origin,'Access-Control-Request-Method':'PUT','Access-Control-Request-Headers':'content-type'})
            assert response.status_code == 200
            assert response.headers['access-control-allow-origin'] == origin
        assert client.options('/api/config',headers={'Origin':'https://untrusted.example','Access-Control-Request-Method':'PUT'}).status_code == 400


def test_relative_db_path_uses_project_root(tmp_path, monkeypatch):
    from backend import main
    project=tmp_path/'project'
    elsewhere=tmp_path/'elsewhere'
    project.mkdir()
    elsewhere.mkdir()
    monkeypatch.setattr(main,'ROOT',project)
    monkeypatch.chdir(elsewhere)
    with TestClient(create_app('data/path-regression.sqlite3',monitoring=False)) as client:
        assert client.get('/api/config').status_code == 200
        assert (project/'data/path-regression.sqlite3').exists()
        assert not (elsewhere/'data/path-regression.sqlite3').exists()


@pytest.mark.parametrize('line',[
    'Reply from ::1: time<1ms bytes=32',
    'Resposta de ::1: tempo<1ms bytes=32',
    'Reply from ::1: time<1ms',
    'Resposta de ::1: tempo<1ms',
])
def test_windows_ipv6_reply_without_ttl(line):
    assert parse_reply(line) == 1


async def test_dns_missing_resolver_is_unknown(monkeypatch):
    def missing():raise probes.dns.resolver.NoResolverConfiguration()
    monkeypatch.setattr(probes.dns.asyncresolver,'Resolver',missing)
    result=await probes.dns_probe('example.com',1)
    assert result.success is None


async def test_storage_failure_joins_sibling_probes(monkeypatch):
    sibling_started=asyncio.Event()
    sibling_cancelled=asyncio.Event()
    class Store:
        def config(self):
            return {'settings':{'interval_seconds':5,'timeout_seconds':1,'ping_count':1,'retention_days':30},
                    'targets':[{'id':1,'kind':'ping','address':'first','enabled':True},
                               {'id':2,'kind':'ping','address':'second','enabled':True}]}
        def record(self,*args):raise OSError('disk full')
    async def probe(address,*args):
        if address=='first':
            await sibling_started.wait()
            return Measurement(True,1)
        sibling_started.set()
        try:await asyncio.sleep(60)
        finally:sibling_cancelled.set()
    monkeypatch.setattr(probes,'ping',probe)
    monitor=Monitor(Store())
    await monitor.start()
    try:
        await asyncio.wait_for(sibling_cancelled.wait(),2)
        for _ in range(100):
            if monitor.error:break
            await asyncio.sleep(.01)
        assert monitor.error
        assert not monitor.lock.locked()
    finally:
        await monitor.stop()
