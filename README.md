# 🔭 PIX DownDetector Monitor for O11y

[![CI](https://github.com/YOUR_ORG/pix-downdetector-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_ORG/pix-downdetector-monitor/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## 📋 Descrição

O **PIX DownDetector Monitor for O11y** é uma solução de monitoramento externo que coleta métricas de disponibilidade e problemas reportados pelos usuários no site [Downdetector Brasil](https://downdetector.com.br/) para serviços financeiros críticos (PIX, Bradesco, Itaú) e as envia automaticamente para a plataforma de observabilidade **Dynatrace**.

### Como funciona

```
┌─────────────────────────────────────────────────────────────────┐
│                        FLUXO DE EXECUÇÃO                        │
│                                                                 │
│  Bright Data Scraping Browser (Proxy Residencial)               │
│         │                                                       │
│         ▼                                                       │
│  downdetector.com.br ──► Playwright Async ──► Parser/Extractor  │
│         (PIX, Bradesco, Itaú)                      │            │
│                                                    ▼            │
│                                         ServiceMetrics          │
│                                                    │            │
│                                                    ▼            │
│                                    Dynatrace Metrics API v2     │
│                                  (custom.downdetector.*)        │
└─────────────────────────────────────────────────────────────────┘
```

**Métricas coletadas por serviço:**
- `feedback_problems` — `0` (sem problemas) ou `1` (problemas detectados)
- `*_pct` — Percentual de reclamações por categoria (ex: transferências, login, app móvel)
- `*_processing_time_ms` — Tempo de processamento em milissegundos

---

## 🗂️ Estrutura do Projeto

```
pix-downdetector-monitor/
├── src/
│   └── downdetector_monitor/
│       ├── __init__.py
│       ├── monitor.py          # Lógica principal (browser automation + Dynatrace)
│       ├── models.py           # Dataclasses: ServiceConfig, ServiceMetrics
│       ├── dynatrace.py        # DynatraceClient (envio de métricas)
│       ├── services.py         # Definição dos serviços monitorados
│       └── utils.py            # Funções utilitárias (normalize_slug, validação)
├── tests/
│   ├── __init__.py
│   ├── test_utils.py
│   ├── test_dynatrace.py
│   └── test_monitor.py
├── docs/
│   ├── dynatrace_setup.md      # Guia de configuração do Dynatrace
│   ├── brightdata_proxy.md     # Guia de configuração do proxy Bright Data
│   └── metrics_reference.md    # Referência de todas as métricas
├── .github/
│   └── workflows/
│       └── ci.yml              # Pipeline CI/CD (GitHub Actions)
├── .env.example                # Template de variáveis de ambiente
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

---

## ⚙️ Pré-requisitos

| Requisito | Versão mínima |
|---|---|
| Python | 3.10+ |
| Conta Bright Data | Scraping Browser habilitado |
| Tenant Dynatrace | SaaS ou Managed |
| Token Dynatrace | Permissão `metrics.ingest` |

---

## 🚀 Instalação e Uso

### 1. Clone o repositório

```bash
git clone https://github.com/YOUR_ORG/pix-downdetector-monitor.git
cd pix-downdetector-monitor
```

### 2. Crie e ative o virtualenv

```bash
python3.10 -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows
```

### 3. Instale as dependências

```bash
pip install -r requirements.txt

# Instale os browsers do Playwright
playwright install chromium
```

### 4. Configure as variáveis de ambiente

```bash
cp .env.example .env
# Edite o arquivo .env com suas credenciais
```

Conteúdo do `.env`:

```dotenv
# Bright Data - Scraping Browser
AUTH=brd-customer-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX:XXXXXXXXXXXXXXXXXX

# Dynatrace
DT_URL=https://XXXXXXXX.live.dynatrace.com
DT_API_TOKEN=dt0c01.XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

### 5. Execute o monitor

```bash
python -m downdetector_monitor.monitor
# ou
python src/downdetector_monitor/monitor.py
```

**Exemplo de saída esperada:**

```
============================================================
🚀 Downdetector Multi-Service Monitor
============================================================
✅ Environment validated
📊 Services to monitor: 3

============================================================
🔍 Monitoring: PIX
🌐 URL: https://downdetector.com.br/fora-do-ar/pix/
   Loading page...
   CAPTCHA status: solve_finished (attempt 1/2)
   ✅ No problems detected
   📊 transferências: 52%
   📊 pagamentos: 31%
   📊 código qr: 17%
📤 Sent 5 metrics for pix

⏳ Waiting 5s before next service...
...
============================================================
📊 SUMMARY
============================================================
✅ Successful: 3/3
❌ Failed: 0/3
✅ pix: 🟢 Problems=0, Metrics=3, Time=42.3s
✅ bradesco: 🟢 Problems=0, Metrics=3, Time=38.1s
✅ itau: 🟢 Problems=0, Metrics=3, Time=40.7s
============================================================
```

---

## 🌐 Proxy Residencial — Bright Data (Obrigatório)

O Downdetector utiliza proteção anti-bot (Cloudflare + CAPTCHAs). Por isso, **é obrigatório** o uso de um proxy com capacidade de resolução automática de CAPTCHA.

### Por que o Bright Data Scraping Browser?

| Funcionalidade | Descrição |
|---|---|
| **CAPTCHA automático** | Resolve Cloudflare, reCAPTCHA e hCaptcha sem intervenção manual |
| **IP residencial** | Simula um navegador real de usuário doméstico |
| **CDP nativo** | Integração direta com Playwright via Chrome DevTools Protocol |
| **Rotação de IP** | Evita bloqueios por rate limiting |

### Como configurar

1. Acesse [brightdata.com](https://brightdata.com) e crie uma conta
2. Crie uma zona do tipo **Scraping Browser**
3. Copie as credenciais no formato: `brd-customer-XXXX:XXXX`
4. Defina no `.env`:

```dotenv
AUTH=brd-customer-XXXXXXXXXXXXXXXX:XXXXXXXXXXXXXXXX
```

> 💡 **Alternativas de proxy:** Oxylabs, Smartproxy ou qualquer provedor com suporte a CDP/WebSocket e resolução de CAPTCHA.

### Endpoint de conexão

O monitor se conecta ao endpoint WebSocket:

```
wss://{AUTH}@brd.superproxy.io:9222
```

---

## 📊 Enviando Métricas ao Dynatrace

### Configuração do Token de API

1. No Dynatrace, acesse **Settings → Access Tokens → Generate new token**
2. Habilite o scope: **`metrics.ingest`** (Ingest metrics)
3. Copie o token gerado (começa com `dt0c01.`)

```dotenv
DT_URL=https://XXXXXXXX.live.dynatrace.com
DT_API_TOKEN=dt0c01.XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

### Métricas enviadas

As métricas seguem a nomenclatura `custom.downdetector.<servico>_<metrica>`:

| Métrica | Tipo | Descrição |
|---|---|---|
| `custom.downdetector.pix_feedback_problems` | Gauge (0/1) | 0=OK, 1=Problemas detectados |
| `custom.downdetector.pix_transferencias_pct` | Gauge (%) | % reclamações de transferência |
| `custom.downdetector.pix_pagamentos_pct` | Gauge (%) | % reclamações de pagamentos |
| `custom.downdetector.pix_codigo_qr_pct` | Gauge (%) | % reclamações de QR Code |
| `custom.downdetector.pix_processing_time_ms` | Gauge (ms) | Tempo de coleta |
| `custom.downdetector.bradesco_feedback_problems` | Gauge (0/1) | 0=OK, 1=Problemas |
| `custom.downdetector.itau_feedback_problems` | Gauge (0/1) | 0=OK, 1=Problemas |

### Endpoint utilizado

```
POST {DT_URL}/api/v2/metrics/ingest
Content-Type: text/plain; charset=utf-8
Authorization: Api-Token {DT_API_TOKEN}

custom.downdetector.pix_feedback_problems,source=downdetector 0
custom.downdetector.pix_transferencias_pct,source=downdetector 52
```

### Criando dashboards e alertas no Dynatrace

Após a primeira execução, as métricas aparecem em:

- **Metrics Explorer:** Busque por `custom.downdetector`
- **Dashboards:** Crie tiles com gráficos de série temporal
- **Alerting:** Configure Davis Anomaly Detection ou alertas baseados em threshold:
  - `custom.downdetector.*_feedback_problems` > 0 → Alerta de indisponibilidade
  - `custom.downdetector.*_pct` > 70 → Alta concentração de problemas

---

## 🧪 Rodando os Testes

### Instale as dependências de desenvolvimento

```bash
pip install -r requirements-dev.txt
```

### Execute os testes

```bash
# Todos os testes
pytest

# Com verbose
pytest -v

# Com cobertura
pytest --cov=src/downdetector_monitor --cov-report=term-missing

# Testes específicos
pytest tests/test_utils.py -v
pytest tests/test_dynatrace.py -v
```

---

## 🐳 Docker

### Build e execução

```bash
# Build da imagem
docker build -t pix-downdetector-monitor .

# Execução com variáveis de ambiente
docker run --rm \
  -e AUTH="brd-customer-XXXX:XXXX" \
  -e DT_URL="https://XXXX.live.dynatrace.com" \
  -e DT_API_TOKEN="dt0c01.XXXX" \
  pix-downdetector-monitor
```

### Docker Compose

```bash
# Configure o .env e execute
docker-compose up
```

---

## 🔄 CI/CD — GitHub Actions

O pipeline roda automaticamente em cada `push` e `pull_request` na branch `main`:

1. **Lint** com `flake8` e `black --check`
2. **Testes** com `pytest`
3. **Cobertura** com `pytest-cov`

Configure os seguintes **Secrets** no repositório GitHub:

| Secret | Descrição |
|---|---|
| `AUTH` | Credencial Bright Data |
| `DT_URL` | URL do tenant Dynatrace |
| `DT_API_TOKEN` | Token de API do Dynatrace |

---

## 📄 Licença

MIT © YOUR_ORG
