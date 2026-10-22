"""Teste manual reproduzível com medições reais, sem expectativas sobre a Internet."""
import asyncio
import json

from backend.probes import detect_gateway, dns_probe, http_probe, ping


async def main():
    gateway = await detect_gateway()
    results = {'gateway': gateway}
    for host in ['127.0.0.1', '1.1.1.1'] + ([gateway] if gateway else []):
        results[f'ping:{host}'] = (await ping(host, 3, 2)).dict()
    results['dns:example.com'] = (await dns_probe('example.com', 3)).dict()
    results['https:example.com'] = (await http_probe('https://example.com', 5)).dict()
    print(json.dumps(results, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    asyncio.run(main())
