# 📊 Guia de Configuração — Dynatrace

## 1. Criar o Token de API

1. Acesse seu tenant Dynatrace: `https://XXXXXXXX.live.dynatrace.com`
2. Navegue até **Settings → Access Tokens → Generate new token**
3. Nome sugerido: `pix-downdetector-monitor`
4. Habilite o scope: **`metrics.ingest`** (Ingest metrics)
5. Clique em **Generate token** e copie o valor (começa com `dt0c01.`)

> ⚠️ O token só é exibido uma vez. Guarde-o em um gerenciador de senhas (ex: Vault, AWS Secrets Manager).

## 2. Variáveis de Ambiente

```dotenv
DT_URL=https://XXXXXXXX.live.dynatrace.com
DT_API_TOKEN=dt0c01.XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

## 3. Métricas Disponíveis

Após a primeira execução, busque no **Metrics Explorer** por `custom.downdetector`:

| Métrica | Tipo | Descrição |
|---|---|---|
| `custom.downdetector.pix_feedback_problems` | Gauge | 0=OK / 1=Problemas |
| `custom.downdetector.pix_transferencias_pct` | Gauge | % de reclamações de transferência |
| `custom.downdetector.pix_pagamentos_pct` | Gauge | % de reclamações de pagamentos |
| `custom.downdetector.pix_codigo_qr_pct` | Gauge | % de reclamações de QR Code |
| `custom.downdetector.pix_processing_time_ms` | Gauge | Tempo de coleta em ms |
| `custom.downdetector.bradesco_feedback_problems` | Gauge | 0=OK / 1=Problemas Bradesco |
| `custom.downdetector.itau_feedback_problems` | Gauge | 0=OK / 1=Problemas Itaú |

## 4. Criar Dashboard

1. **Dashboards → Create dashboard**
2. Adicione tiles do tipo **Metric**:
   - Selecione `custom.downdetector.pix_feedback_problems`
   - Visualização: **Single value** com coloração por threshold (0=verde, 1=vermelho)
3. Adicione tiles de série temporal para os percentuais

## 5. Criar Alertas (Davis Anomaly Detection)

### Alerta: PIX com Problemas

1. **Settings → Anomaly Detection → Custom metric events**
2. **Create metric event:**
   - Nome: `PIX — Problemas Detectados no Downdetector`
   - Métrica: `custom.downdetector.pix_feedback_problems`
   - Condição: **Rises above** `0.5` por `1` ocorrência
   - Severidade: `ERROR`

### Alerta: Alta Concentração de Reclamações

1. Nome: `PIX — Alta % de Reclamações de Transferências`
2. Métrica: `custom.downdetector.pix_transferencias_pct`
3. Condição: **Rises above** `70` (70%)
4. Severidade: `WARNING`

## 6. Verificar Ingestão via API (Debug)

```bash
curl -X GET \
  "https://XXXXXXXX.live.dynatrace.com/api/v2/metrics/query?metricSelector=custom.downdetector.pix_feedback_problems" \
  -H "Authorization: Api-Token dt0c01.XXXX" \
  -H "Accept: application/json"
```
