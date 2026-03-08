# 🌐 Guia de Configuração — Bright Data Scraping Browser

## Por que um Proxy Residencial?

O Downdetector utiliza **Cloudflare** e sistemas anti-bot avançados. Sem um proxy residencial com suporte a resolução de CAPTCHA, o scraping falha imediatamente.

## Passo a Passo — Bright Data

### 1. Criar Conta

1. Acesse [brightdata.com](https://brightdata.com) e crie uma conta
2. Complete a verificação de identidade

### 2. Criar Zona do Tipo Scraping Browser

1. No painel, clique em **Add Zone**
2. Tipo: **Scraping Browser**
3. Nome: `downdetector-monitor`
4. Clique em **Save**

### 3. Obter Credenciais

As credenciais ficam na aba **Overview** da zona:

```
Host: brd.superproxy.io
Port: 9222 (CDP/WebSocket)
Username: brd-customer-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
Password: XXXXXXXXXXXXXXXXXXXXXXXX
```

Formato para o `.env`:

```dotenv
AUTH=brd-customer-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX:XXXXXXXXXXXXXXXXXXXXXXXX
```

### 4. Endpoint de Conexão

O monitor se conecta via WebSocket CDP:

```
wss://{AUTH}@brd.superproxy.io:9222
```

O Playwright se conecta a este endpoint e o Bright Data gerencia:
- Resolução automática de CAPTCHA (Cloudflare, reCAPTCHA, hCaptcha)
- Rotação de IPs residenciais
- Fingerprint de browser real

## Alternativas de Proxy

| Provedor | Produto | Notas |
|---|---|---|
| [Oxylabs](https://oxylabs.io) | Web Scraper API | Suporte a CAPTCHA |
| [Smartproxy](https://smartproxy.com) | Scraping API | Boa cobertura BR |
| [ScraperAPI](https://scraperapi.com) | API REST | Mais simples de integrar |
| [ZenRows](https://zenrows.com) | API REST | Anti-bot nativo |

> Para usar uma alternativa, altere `endpoint_url` em `DowndetectorMonitor.__init__()`.

## Estimativa de Custo (Bright Data)

- Cada execução consome ~3-5 MB de dados (3 serviços)
- Com execução a cada 5 min: ~2-3 GB/dia
- Verifique o plano atual em **Billing → Usage**
