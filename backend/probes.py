"""Sondas reais; subprocessos sem shell e com cancelamento explícito."""
import asyncio
import ipaddress
import math
import os
import re
import statistics
import time
from dataclasses import asdict, dataclass

import dns.asyncresolver
import httpx
from . import __version__


@dataclass
class Measurement:
    success: bool | None
    latency_ms: float | None = None
    jitter_ms: float | None = None
    packet_loss: float | None = None
    sent: int = 0
    received: int = 0
    error: str | None = None

    def dict(self):
        return asdict(self)


async def command(*args: str, timeout: float) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        **({"creationflags": 0x08000000} if os.name == "nt" else {}),
    )
    try:
        output, _ = await asyncio.wait_for(proc.communicate(), timeout)
        return proc.returncode or 0, output.decode("oem" if os.name == "nt" else "utf-8", errors="replace")
    except (asyncio.TimeoutError, asyncio.CancelledError):
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await proc.communicate()
        raise


def parse_reply(output: str) -> float | None:
    # Windows IPv6 replies may omit both TTL and bytes; require an echo-reply prefix.
    for line in output.splitlines():
        if not re.search(r"(?:ttl|hlim)[=\s]|bytes\s*=|^\s*(?:reply from|resposta de|r[eé]ponse de|antwort von|respuesta (?:de|desde))\s", line, re.I):
            continue
        match = re.search(r"(?:time|tempo|temps|zeit|tiempo)\s*([=<])\s*(\d+(?:[.,]\d+)?)\s*ms", line, re.I)
        if match:
            # '<1 ms' is represented by its upper bound, never a fabricated RTT.
            return float(match[2].replace(",", "."))
    return None


async def ping(address: str, count: int, timeout: float) -> Measurement:
    rtts = []
    replies = 0
    unknown = 0
    last_error = None
    for _ in range(count):
        args = (["ping", "-n", "1", "-w", str(math.ceil(timeout * 1000)), address]
                if os.name == "nt" else
                ["ping", "-n", "-c", "1", "-W", str(math.ceil(timeout)), address])
        try:
            code, output = await command(*args, timeout=timeout + 1.5)
            rtt = parse_reply(output)
            if rtt is not None:
                replies += 1
                rtts.append(rtt)
            elif code == 0 and re.search(r"(?:ttl|hlim)[=\s]", output, re.I):
                replies += 1
                last_error = "Resposta ICMP recebida; RTT não reconhecido neste idioma"
            elif re.search(r'unreachable|inacess|timed out|esgotado', output, re.I):
                last_error = "Sem resposta ICMP (timeout ou destino inacessível)"
            elif code == 0:
                unknown += 1
                last_error = "Resposta ping não reconhecida; verifique idioma e permissões"
            elif code > 1 or re.search(r'operation not permitted|permission denied|access denied|acesso negado|general failure|falha geral', output, re.I):
                unknown += 1
                last_error = "Falha local do ping; verifique endereço, permissões e configuração da rede"
            else:
                last_error = "Sem resposta ICMP (timeout, destino inacessível ou ICMP bloqueado)"
        except FileNotFoundError:
            return Measurement(None, error="Executável ping ausente; instale iputils-ping")
        except asyncio.TimeoutError:
            last_error = "Timeout do ping"
        except OSError as exc:
            return Measurement(None, error=f"Falha ao executar ping: {exc}")
    jitter = statistics.mean(abs(b - a) for a, b in zip(rtts, rtts[1:])) if len(rtts) > 1 else None
    known = count - unknown
    return Measurement(replies > 0 if known else None, statistics.mean(rtts) if rtts else None, jitter,
                       100 * (known - replies) / known if known else None, known, replies,
                       last_error if replies < count or len(rtts) < replies else None)


async def dns_probe(address: str, timeout: float) -> Measurement:
    started = time.perf_counter()
    try:
        resolver = dns.asyncresolver.Resolver()
        resolver.cache = None
        await resolver.resolve(address, "A", lifetime=timeout, search=False)
        return Measurement(True, (time.perf_counter() - started) * 1000)
    except dns.resolver.NoResolverConfiguration as exc:
        return Measurement(None, error=f"Configuração DNS local indisponível: {exc}"[:300])
    except Exception as exc:
        return Measurement(False, error=f"DNS: {type(exc).__name__}: {exc}"[:300])


async def http_probe(address: str, timeout: float) -> Measurement:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=False) as client:
            # Deadline covers the whole redirect chain; no response body is downloaded.
            async with asyncio.timeout(timeout):
                async with client.stream("GET", address, headers={"User-Agent": f"NetPulse/{__version__}"}) as response:
                    elapsed = (time.perf_counter() - started) * 1000
                    return Measurement(response.status_code < 400, elapsed,
                                       error=f"HTTP {response.status_code}" if response.status_code >= 400 else None)
    except Exception as exc:
        return Measurement(False, error=f"HTTP: {type(exc).__name__}: {exc}"[:300])


async def detect_gateway() -> str | None:
    try:
        args = ("route", "print", "-4") if os.name == "nt" else ("ip", "-4", "route", "show", "default")
        _, output = await command(*args, timeout=3)
        if os.name == "nt":
            matches = re.findall(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)\s+\S+\s+(\d+)", output, re.M)
            gateway = min(matches, key=lambda m: int(m[1]))[0] if matches else None
        else:
            match = re.search(r"default via (\S+)", output)
            gateway = match[1] if match else None
        if gateway and not ipaddress.ip_address(gateway).is_unspecified:
            return gateway
    except (OSError, ValueError, asyncio.TimeoutError):
        pass
    return None
