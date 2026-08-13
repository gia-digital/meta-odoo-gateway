# Chatwoot Agent Bot — GIA

El gateway actúa como **Agent Bot** de Chatwoot: recibe mensajes del inbox WhatsApp,
responde con OpenAI Agents SDK + LiteLLM (Anthropic u OpenAI) y registra leads
con la misma lógica que `POST /leads`.

## Arquitectura

```
WhatsApp → Chatwoot inbox (Agent Bot)
              ↓ POST /webhook/chatwoot
         FastAPI gateway
              ├─ agent_info + docs/agent_prompt.md
              ├─ tools: create_lead, escalate_to_human
              └─ Chatwoot API (mensaje outgoing / status open)
```

## 1. Crear el bot en Chatwoot

1. Settings → **Bots** → Add Bot.
2. Name: `GIA Sales Agent` (o similar).
3. Webhook URL / outgoing URL:

   `https://<tu-dominio-gateway>/webhook/chatwoot`

   Ejemplo: `https://gia.init.com.mx/webhook/chatwoot`

4. Copia el **access_token** del bot → `CHATWOOT_BOT_TOKEN`.
5. Si Chatwoot muestra un webhook secret → `CHATWOOT_WEBHOOK_SECRET`.

## 2. Conectar el inbox

Inbox de WhatsApp → **Bot Configuration** → selecciona este bot → Save.

Las conversaciones nuevas quedan en status **pending** mientras el bot atiende.
Al escalar, el bot pone status **open** para humanos.

## 3. Variables de entorno

Ver [`.env.example`](../.env.example):

```bash
CHATWOOT_ENABLED=true
CHATWOOT_BASE_URL=https://chat.tuempresa.com
CHATWOOT_ACCOUNT_ID=1
CHATWOOT_BOT_TOKEN=...
CHATWOOT_WEBHOOK_SECRET=   # opcional

# Preferencia cliente: Anthropic. Cambiar a OpenAI para costo.
AGENT_MODEL=anthropic/claude-sonnet-4-20250514
ANTHROPIC_API_KEY=sk-ant-...
# AGENT_MODEL=openai/gpt-4.1-mini
# OPENAI_API_KEY=sk-...
```

Reinicia el API tras cambiar env.

## 4. Knowledge reutilizada

| Fuente | Uso |
|--------|-----|
| `docs/agent_prompt.md` | Instrucciones base |
| `agent_info/skills.json` | Skills operativos |
| `agent_info/business_info.json` | Datos de negocio |
| `agent_info/faqs.json` | FAQs (truncadas por `AGENT_FAQ_CHAR_LIMIT`) |

Cambios en esos archivos requieren **reinicio** del proceso (instructions cacheadas).

## 5. Tools del agente

- **create_lead** — same fields as Meta tool; `qualification_source=chatwoot_agent`; visible en `/dashboard/leads`.
- **escalate_to_human** — marca handoff en DB + `toggle_status` → `open` en Chatwoot.

## 6. Prueba rápida

1. Escribe al WhatsApp Business conectado a Chatwoot.
2. Debe aparecer reply del bot en el hilo.
3. Pide cotización con toneladas → debe crear lead.
4. Pide “hablar con un asesor” → conversación pasa a **open**.

## 7. Troubleshooting

| Síntoma | Causa típica |
|---------|----------------|
| Chatwoot: *error with the agent bot* + logs `401` en `/webhook/chatwoot` | Firma HMAC inválida. Chatwoot firma `HMAC(secret, "{timestamp}.{body}")` con `X-Chatwoot-Signature` + `X-Chatwoot-Timestamp`. Confirma que `CHATWOOT_WEBHOOK_SECRET` sea el **secret del bot** (no el access token). |
| Desbloqueo rápido | Vacía `CHATWOOT_WEBHOOK_SECRET=` en `.env`, recrea el contenedor `api`, vuelve a probar. Luego restaura el secret con un deploy que tenga la verificación correcta. |
| Bot no responde pero HTTP 200 | Conversación no está en status `pending`, o falta `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`. |

## 8. Dependencias

```bash
pip install -r requirements.txt
# incluye openai-agents[litellm]
```

Docs SDK: [OpenAI Agents Python](https://github.com/openai/openai-agents-python) · LiteLLM multi-provider.
