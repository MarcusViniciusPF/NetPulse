import asyncio
import sys
from unittest.mock import AsyncMock

import pytest
import httpx

from backend import probes


@pytest.mark.parametrize('text,expected', [
    ('Reply from 1.1.1.1: bytes=32 time=12ms TTL=57', 12),
    ('Resposta de 1.1.1.1: bytes=32 tempo<1ms TTL=128', 1),
    ('64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=3.42 ms', 3.42),
    ('64 bytes from ::1: icmp_seq=1 hlim=64 time=0,12 ms', .12),
    ('From 192.168.1.1: Destination Host Unreachable', None),
    ('Minimum = 1ms, Maximum = 5ms, Average = 3ms', None),
    ('Request timed out.', None),
])
def test_parse(text, expected):
    assert probes.parse_reply(text) == expected


async def test_ping_partial_and_jitter(monkeypatch):
    mock = AsyncMock(side_effect=[(0,'Reply: time=10ms TTL=57'),(1,'Timeout'),(0,'Reply: time=16ms TTL=57')])
    monkeypatch.setattr(probes,'command',mock)
    result = await probes.ping('127.0.0.1',3,.2)
    assert result.success is True
    assert result.sent == 3 and result.received == 2
    assert result.latency_ms == 13 and result.jitter_ms == 6
    assert result.packet_loss == pytest.approx(100/3)
    args = mock.call_args.args
    assert '-n' in args
    assert '127.0.0.1' == args[-1]


async def test_missing_ping_is_collection_error(monkeypatch):
    monkeypatch.setattr(probes,'command',AsyncMock(side_effect=FileNotFoundError))
    result = await probes.ping('127.0.0.1',3,1)
    assert result.success is None and result.packet_loss is None


async def test_timeout_and_total_loss(monkeypatch):
    monkeypatch.setattr(probes,'command',AsyncMock(side_effect=asyncio.TimeoutError))
    result = await probes.ping('127.0.0.1',2,.2)
    assert result.success is False and result.packet_loss == 100
    assert result.latency_ms is None and result.jitter_ms is None


async def test_local_ping_failure_is_unknown(monkeypatch):
    monkeypatch.setattr(probes,'command',AsyncMock(return_value=(2,'ping: socket: Operation not permitted')))
    result = await probes.ping('127.0.0.1',2,.2)
    assert result.success is None and result.packet_loss is None and result.sent == 0


async def test_windows_unreachable_exit_zero_is_failure(monkeypatch):
    monkeypatch.setattr(probes,'command',AsyncMock(return_value=(0,'Resposta de 192.168.1.1: Host de destino inacessivel.')))
    result = await probes.ping('192.0.2.1',1,.2)
    assert result.success is False and result.packet_loss == 100


async def test_linux_ping_arguments(monkeypatch):
    mock=AsyncMock(return_value=(0,'64 bytes: ttl=64 time=0.1 ms'))
    monkeypatch.setattr(probes.os,'name','posix')
    monkeypatch.setattr(probes,'command',mock)
    await probes.ping('::1',1,1.3)
    assert mock.call_args.args == ('ping','-n','-c','1','-W','2','::1')


async def test_command_timeout_and_cancel():
    with pytest.raises(asyncio.TimeoutError):
        await probes.command(sys.executable,'-c','import time; time.sleep(30)',timeout=.1)
    task = asyncio.create_task(probes.command(sys.executable,'-c','import time; time.sleep(30)',timeout=30))
    await asyncio.sleep(.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_dns_success_and_failure(monkeypatch):
    resolve = AsyncMock(return_value=object())
    monkeypatch.setattr(probes.dns.asyncresolver.Resolver,'resolve',resolve)
    assert (await probes.dns_probe('example.com',1)).success is True
    resolve.side_effect = Exception('NXDOMAIN')
    assert (await probes.dns_probe('example.com',1)).success is False


async def test_http_real_local_server():
    async def handler(reader,writer):
        await reader.readuntil(b'\r\n\r\n')
        writer.write(b'HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n')
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    server = await asyncio.start_server(handler,'127.0.0.1',0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        result = await probes.http_probe(f'http://127.0.0.1:{port}',2)
        assert result.success is True and result.latency_ms > 0
    result = await probes.http_probe(f'http://127.0.0.1:{port}',.2)
    assert result.success is False and result.latency_ms is None
