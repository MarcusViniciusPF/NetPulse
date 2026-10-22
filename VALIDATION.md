# Validação do MVP

Execução em **21/10/2026**, no Windows x64 deste workspace. Python 3.12.10 e Node.js 22.16.0 portáteis em `.tools/` (não versionados).

## Resultados automatizados

| Verificação | Resultado |
| --- | --- |
| `python -m pytest -q` | 35 testes aprovados |
| `npm test` | 4 testes aprovados |
| `npm run build` | TypeScript e produção compilados com sucesso |
| `python -m pip check` | Nenhuma dependência incompatível |
| `npm run test:browser` | Chrome headless: frontend Vite e frontend compilado, desktop e móvel, sem erros de console/runtime |

Cobertura funcional dos testes:

- Parsing de ping Windows em inglês/português, Linux e respostas com vírgula decimal; descarte de resumos e respostas inacessíveis.
- Cálculo de média, jitter, perda parcial/total, timeout, comando ausente e falha local de permissões.
- Argumentos de ping Linux; encerramento de subprocesso por timeout e cancelamento.
- DNS com resultados controlados e HTTP real com servidor loopback.
- Persistência após reabrir SQLite, retenção, agregação de histórico, abertura única e recuperação de quedas.
- Alterações atômicas de configuração, preservação do histórico, remoção e rejeição de endereços inválidos.
- API, validação de limites e isolamento de falhas de sondas.
- Uvicorn real em loopback com ping/HTTP reais, consulta REST, gravação em banco temporário, entrega do HTML compilado e encerramento pelo ciclo de vida do servidor.
- Interface: apresentação de valores ausentes, diferenciação de estados, detecção de dados antigos, duração e lacunas explícitas nos gráficos.
- Regressões: `/health`, CORS com espaços/barras finais, rejeição de origem não permitida, caminho relativo de banco fora da raiz, ping IPv6 Windows sem TTL/bytes, DNS sem configuração local e cancelamento de sondas irmãs após falha de gravação.
- Queda e recuperação HTTP reais em servidor loopback: resposta 200 → 503 → 200, detectadas pelo coletor e verificadas nos eventos persistidos.
- Chrome instalado: chamadas reais via proxy Vite e por CORS direto, renderização dos gráficos e seus pontos, troca de período, abertura e salvamento da configuração sem alterações, histórico de eventos e layout de 390px sem overflow global. Captura móvel inspecionada. Relatório e capturas em `.tools/validation/`.

Uma advertência de depreciação vem do TestClient da versão instalada do Starlette sobre o adaptador httpx. Não houve falha; a integração HTTP real também foi testada sem TestClient.

## Diagnóstico real de rede

`python -m scripts.smoke` foi executado com acesso de rede autorizado. Estes são resultados pontuais observados, não dados inseridos na aplicação nem garantias de desempenho futuro:

| Sonda | Resultado observado |
| --- | --- |
| Descoberta do gateway IPv4 | Detectado |
| Ping loopback `127.0.0.1` | 3/3 respostas, sem perda |
| Ping IPv6 loopback `::1` | 3/3 respostas, sem perda, após corrigir o parser |
| Ping gateway | 3/3 respostas, sem perda |
| Ping `1.1.1.1` | 3/3 respostas, média 29 ms, sem perda |
| DNS A `example.com` | Sucesso, aproximadamente 34,4 ms |
| HTTPS `https://example.com` | Sucesso, aproximadamente 490,1 ms |

O Windows reportou RTT abaixo de 1 ms para loopback/gateway; a sonda conserva o limite superior de 1 ms, conforme documentado no README. As dependências Python foram conferidas e as Node reinstaladas por `npm ci`; `playwright-core` foi acrescentado apenas para os testes do navegador, sem uso na aplicação.

Foram consultados `/health`, `/api/health`, `/api/config`, `/api/dashboard`, `/docs`, `/openapi.json` e o proxy `/api` do Vite. Métricas atuais ficam em `targets[].latest`; séries históricas em `history`, no mesmo endpoint de dashboard. O banco real `data/netpulse.sqlite3` passou em `PRAGMA integrity_check` (`ok`) e `foreign_key_check` (sem erros), com múltiplos ciclos gravados para cinco destinos. Em uma conferência, as **55 linhas do banco** corresponderam exatamente às **55 amostras nas estatísticas e nas séries históricas da API**. Os gráficos consultaram esse histórico real pelo navegador.

Corrigidos nesta validação: alias `/health`, normalização CORS, resolução de caminho do SQLite, código de saúde quando coletor parado, decodificação OEM do Windows, parsing IPv6, classificação de DNS sem resolvedor como erro de coleta, cancelamento de sondas após falha no banco, porta fixa do Vite, favicon ausente e visibilidade das amostras isoladas nos gráficos. A primeira execução pytest desta etapa falhou por permissões nos temporários herdados; corrigida a configuração para usar diretórios locais dedicados e repetida a suíte. O primeiro teste de navegador também identificou o favicon 404; corrigido e repetido sem erros.

## Pendências de validação manual

- Revisão exaustiva de acessibilidade por teclado/leitor de tela, tooltips e todas as combinações de campos inválidos pelo navegador. A validação de payloads inválidos da API foi executada automaticamente.
- Desconexão física de Wi-Fi/cabo e recuperação de conexão real. Quedas/recuperações HTTP foram verificadas com tráfego real de loopback; perda de pacotes foi exercitada com saídas controladas e tráfego ICMP real sem perda observada.
- Ctrl+C em um terminal interativo, SIGTERM sob systemd, VPN/múltiplos gateways, IPv6 externo e outros idiomas do Windows. IPv6 loopback, timeout/cancelamento e shutdown do servidor foram testados.
- Execução em Linux e Raspberry Pi OS 64-bit: sintaxe do comando Linux foi verificada por teste, sem uma máquina Linux neste ambiente.
- Raspberry Pi 5: instalação ARM64, permissões de ICMP como usuário de serviço, unidade systemd, uso de CPU/RAM, temperatura, armazenamento, perda de energia e estabilidade prolongada.

O modelo systemd e as instruções de implantação estão em `deploy/` e no README. Na validação inicial de 21/10 não houve criação de repositório Git. A preparação local de 22/10 está descrita a seguir; não houve envio para GitHub.

## Preparação da versão 0.1.0 — 22/10/2026

### Verificações executadas nesta etapa

| Verificação | Resultado local |
| --- | --- |
| Ambiente virtual novo com CPython 3.12.15 e `pip install -r requirements-dev.txt` | Instalado com sucesso |
| `python -m pytest -q` no ambiente novo | 35 testes aprovados |
| `python -m pip check` | Sem incompatibilidades |
| `npm ci`, `npm test`, `npm run build` | 4 testes aprovados; TypeScript/build concluídos |
| Testes Python em cópia limpa do índice Git, sem `.tools`, banco, `.venv` ou dependências na cópia | 35 testes aprovados |
| `npm ci`, testes e build nessa cópia limpa | 4 testes aprovados; build concluído |
| `npm run test:browser` | Aprovado em Vite/produção, desktop/móvel, sem erros de console/runtime |
| YAML do GitHub Actions | Analisado localmente; jobs, matrizes e permissões conferidos |

O ambiente virtual padrão foi criado com `python -m venv`; Python/Node usados como ferramentas locais não são incluídos no repositório. A cópia limpa demonstra que o código e os testes não usam caminhos ou arquivos de `.tools`. O teste de caminho do banco agora usa apenas diretórios temporários de teste; relatórios do navegador ficam em `artifacts/browser/`, ignorados pelo Git.

As capturas de `docs/screenshots/` foram geradas em 22/10 no Chrome, com backend real e banco de captura separado, usando apenas destinos públicos. Foram inspecionadas e copiadas sem alterações de pixels. Esse banco não é versionado e não substitui os dados locais do usuário. A única alteração visível na interface nesta etapa foi a identificação da versão 0.1.0, sem redesenho.

A instalação nova resolveu FastAPI 0.160.0, em lugar do 0.159.1 usado na etapa anterior. O conjunto efetivamente instalado está registrado em `requirements.lock.txt`. Permanece o aviso de depreciação do adaptador TestClient/HTTPX; os testes passaram, inclusive a integração com Uvicorn real.

O workflow usa ações oficiais fixadas por SHA, permissões somente de leitura e matrizes Windows/Linux (Python 3.11/3.12 e Node 22). **GitHub Actions ainda não executou**, pois não houve publicação. A análise de YAML não substitui a execução no runner. Linux, Python 3.11 em execução e Raspberry Pi continuam pendentes de validação prática nesta máquina.

O `.gitignore` exclui runtimes locais, dependências, builds, bancos, caches, logs, arquivos reais de ambiente e padrões de credenciais; o `.env.example` permanece versionado. Nenhuma licença foi adicionada, conforme escolha do autor. O repositório local usa a branch `main` e a identidade fornecida pelo autor; não foi configurado remoto nem executado push.

A revisão automática do ambiente bloqueou a remoção física dos temporários locais (motivo retornado: `blocked by policy`), inclusive a tentativa restrita a arquivos de download/cache. Assim, caches antigos, arquivos de instalação e a cópia local de revisão podem permanecer no disco, todos ignorados pelo Git. A revisão dos 37 arquivos preparados não encontrou esses artefatos, banco local, arquivos reais de ambiente, chaves privadas ou padrões comuns de tokens. Não foi alterado o banco local do usuário.

### Execução convencional

As instruções atuais usam Python/Node convencionais, sem runtimes versionados. Na raiz de uma cópia do projeto com `.venv` criado e dependências instaladas, use dois terminais:

```powershell
# Terminal 1 — backend e dashboard compilado
.\.venv\Scripts\python.exe -m backend.main
```

```powershell
# Terminal 2 — frontend em desenvolvimento
cd frontend
npm run dev
```

Dashboard em desenvolvimento: **http://127.0.0.1:5173**. Dashboard compilado servido pelo backend: **http://127.0.0.1:8000**. Se só quiser usar o sistema, o terminal 1 é suficiente.
