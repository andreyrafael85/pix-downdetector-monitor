# 📐 Referência de Métricas — PIX DownDetector Monitor

## Nomenclatura

```
custom.downdetector.<serviço>_<indicador>
```

## Métricas por Serviço

### PIX

| Métrica | Valores | Descrição |
|---|---|---|
| `custom.downdetector.pix_feedback_problems` | `0` / `1` | Status geral: 0=OK, 1=Problema |
| `custom.downdetector.pix_transferencias_pct` | `0`–`100` | % reclamações de transferências |
| `custom.downdetector.pix_pagamentos_pct` | `0`–`100` | % reclamações de pagamentos |
| `custom.downdetector.pix_codigo_qr_pct` | `0`–`100` | % reclamações de QR Code |
| `custom.downdetector.pix_website_pct` | `0`–`100` | % reclamações de website |
| `custom.downdetector.pix_compras_pct` | `0`–`100` | % reclamações de compras |
| `custom.downdetector.pix_login_pct` | `0`–`100` | % reclamações de login |
| `custom.downdetector.pix_aplicativo_movel_pct` | `0`–`100` | % reclamações de app móvel |
| `custom.downdetector.pix_processing_time_ms` | `ms` | Tempo de coleta em milissegundos |

### Bradesco

| Métrica | Valores | Descrição |
|---|---|---|
| `custom.downdetector.bradesco_feedback_problems` | `0` / `1` | Status geral |
| `custom.downdetector.bradesco_pix_pessoa_fisica_pct` | `0`–`100` | % reclamações PIX PF |
| `custom.downdetector.bradesco_bradesco_net_empresa_pct` | `0`–`100` | % reclamações Net Empresa |
| `custom.downdetector.bradesco_aplicativo_pessoa_fisica_pct` | `0`–`100` | % reclamações App PF |
| `custom.downdetector.bradesco_processing_time_ms` | `ms` | Tempo de coleta |

### Itaú

| Métrica | Valores | Descrição |
|---|---|---|
| `custom.downdetector.itau_feedback_problems` | `0` / `1` | Status geral |
| `custom.downdetector.itau_login_no_aplicativo_movel_pct` | `0`–`100` | % reclamações login app |
| `custom.downdetector.itau_operacoes_no_internet_banking_pct` | `0`–`100` | % reclamações IB |
| `custom.downdetector.itau_pix_pct` | `0`–`100` | % reclamações PIX |
| `custom.downdetector.itau_processing_time_ms` | `ms` | Tempo de coleta |

## Formato de Ingestão (Dynatrace Metrics v2)

```
custom.downdetector.pix_feedback_problems,source=downdetector 0
custom.downdetector.pix_transferencias_pct,source=downdetector 52
custom.downdetector.pix_processing_time_ms,source=downdetector 42350
```

## Lógica de `feedback_problems`

| Condição | Valor |
|---|---|
| Frase esperada encontrada na página | `0` (sem problemas) |
| Frase esperada NÃO encontrada | `1` (problemas detectados) |
| Erro de conexão / timeout | `1` (assume problema) |

A frase esperada é a mensagem que o Downdetector exibe quando não há incidentes ativos, por exemplo:
> *"relatos de usuários indicam que não há problemas atuais com pix"*
