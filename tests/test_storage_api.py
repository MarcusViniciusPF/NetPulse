import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.models import Configuration, Settings, Target
from backend.probes import Measurement
from backend.storage import Store
from backend.monitor import Monitor


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path/'test.sqlite3'))
    s.seed(None)
    return s


def test_transitions_persistence_and_unknown(store):
    target = store.config()['targets'][0]['id']
    store.record(target,Measurement(False,sent=3,received=0,packet_loss=100))
    store.record(target,Measurement(False,sent=3,received=0,packet_loss=100))
    store.record(target,Measurement(None,error='ping ausente'))
    d = Store(store.path).dashboard(24)
    assert len(d['outages']) == 1 and d['outages'][0]['recovered_at'] is None
    store.record(target,Measurement(True,10,2,0,3,3))
    d = store.dashboard(24)
    assert d['outages'][0]['end_reason'] == 'recovered'
    assert d['targets'][0]['stats']['availability'] == pytest.approx(100/3)
    assert d['targets'][0]['stats']['packet_loss'] == pytest.approx(200/3)


def test_config_atomic_preserves_history(store):
    config = Configuration(**store.config())
    first = config.targets[0]
    store.record(first.id,Measurement(False))
    config.targets[0].address = '9.9.9.9'
    config.settings.interval_seconds=10
    with pytest.raises(ValueError):store.save_config(config)
    assert store.config()['settings']['interval_seconds'] == 30
    config = Configuration(**store.config())
    config.targets.pop(0)
    store.save_config(config)
    assert len(store.dashboard(24)['outages']) == 1
    assert store.dashboard(24)['outages'][0]['end_reason'] == 'removed'
    store.record(first.id,Measurement(False))
    assert len(store.dashboard(24)['outages']) == 1


def test_retention_and_buckets(store):
    target = store.config()['targets'][0]['id']
    for i in range(12):store.record(target,Measurement(True,float(i),0,0,1,1))
    with store.connection() as db:
        old=(datetime.now(timezone.utc)-timedelta(days=40)).isoformat()
        db.execute('UPDATE measurements SET timestamp=? WHERE id=1',(old,))
    store.prune(30)
    d=store.dashboard(24,target)
    assert d['targets'][0]['stats']['samples'] == 11
    assert len(d['history']) <= 2
    assert all(p['target_id']==target for p in d['history'])


def test_api(tmp_path):
    with TestClient(create_app(str(tmp_path/'api.sqlite3'),monitoring=False)) as client:
        assert client.get('/api/health').json()['mode'] == 'real'
        config = client.get('/api/config').json()
        assert len(config['targets']) == 4
        assert client.get('/api/dashboard').json()['history'] == []
        config['settings']['interval_seconds']=5
        assert client.put('/api/config',json=config).status_code == 200
        config['settings']['interval_seconds']=0
        assert client.put('/api/config',json=config).status_code == 422
        assert client.get('/api/dashboard?hours=0').status_code == 422
        config=client.get('/api/config').json()
        config['targets'][0]['address']='-n 100 evil; rm'
        assert client.put('/api/config',json=config).status_code == 422
        assert client.get('/api/unknown').status_code == 404


@pytest.mark.parametrize('kind,address',[('ping','-n'),('dns','x;whoami'),('http','file:///etc/passwd'),('http','https://user:pass@example.com'),('http','https://example.com:bad')])
def test_invalid_targets(kind,address):
    with pytest.raises(ValueError):Target(name='Teste',kind=kind,address=address)


async def test_monitor_isolates_errors_and_stops(store,monkeypatch):
    from backend import probes
    async def broken(*args):raise RuntimeError('falha isolada')
    async def healthy(*args):return Measurement(True,1)
    monkeypatch.setattr(probes,'ping',broken)
    monkeypatch.setattr(probes,'dns_probe',healthy)
    monkeypatch.setattr(probes,'http_probe',healthy)
    monitor=Monitor(store)
    await monitor.start()
    for _ in range(100):
        if monitor.last_cycle:break
        await asyncio.sleep(.01)
    await monitor.stop()
    assert monitor.task.done() and monitor.last_cycle
    d=store.dashboard(24)
    assert d['targets'][0]['latest']['success'] is None
    assert d['targets'][2]['latest']['success'] == 1
    assert not d['outages']
