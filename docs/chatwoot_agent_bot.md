# Chatwoot Agent Bot — GIA

El gateway actúa como **Agent Bot** de Chatwoot: recibe mensajes del inbox WhatsApp,
responde con OpenAI Agents SDK (OpenAI → **Responses API**; Anthropic → LiteLLM)
y registra leads con la misma lógica que `POST /leads`.

## Arquitectura

```
WhatsApp → Chatwoot inbox (Agent Bot)
              ↓ POST /webhook/chatwoot
         FastAPI gateway
              ├─ Postgres knowledge (FAQs, negocio, skills, files + pgvector)
              ├─ tools: create_lead, escalate_to_human, search_knowledge, send_catalog
              └─ Chatwoot API (mensaje outgoing / adjunto PDF / status open)
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

# OpenAI usa Responses API (no chat/completions). Anthropic vía LiteLLM.
AGENT_MODEL=openai/gpt-5.6-luna
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
KNOWLEDGE_RETRIEVE_K=8
# AGENT_MODEL=openai/gpt-4.1-mini
# AGENT_MODEL=anthropic/claude-sonnet-4-20250514
# ANTHROPIC_API_KEY=sk-ant-...
```

Reinicia el API tras cambiar env.

## 4. Knowledge (RAG editable)

El bot **no** mete todas las FAQs en el system prompt. El conocimiento vive en Postgres + **pgvector** y se edita en:

`https://gia.init.com.mx/dashboard/knowledge`

| Tipo | Dónde |
|------|--------|
| Instrucciones / políticas | pestaña Instrucciones (tono, catálogo, mínimos; van al system prompt) |
| Negocio | pestaña Negocio |
| FAQs / Skills / Archivos | CRUD + indexado (embeddings) |
| Tools | solo lectura (`create_lead`, `escalate_to_human`, `search_knowledge`, `send_catalog`) |
| Agente | pausas, burbujas y espera por más mensajes (defaults del `.env`) |

Seed inicial al primer boot desde `agent_info/*.json` y PDFs de presentación (no se ingiere `conversaciones_whatsapp.txt`). Cambios en el dashboard aplican **sin redeploy**.

Por cada mensaje: retrieval híbrido (cosine `<=>` + keywords) e inyección de top-k. `search_knowledge` pide más contexto si hace falta.

## 5. Tools del agente

- **create_lead** — registra prospecto calificado (`qualification_source=chatwoot_agent`); visible en `/dashboard/leads`.
- **escalate_to_human** — marca handoff en DB + `toggle_status` → `open` en Chatwoot. El bot **sigue contestando** hasta que un humano escriba al cliente.
- **search_knowledge** — RAG sobre FAQs/skills/files en pgvector.
- **send_catalog** — adjunta `Carta Presentación GIA.pdf` al hilo (WhatsApp) cuando piden catálogo o carta de presentación. No es la lista de precios ni la presentación corporativa 2027. Cada conversación sube el PDF de nuevo (WhatsApp no reutiliza el archivo entre clientes); en el mismo hilo no se reenvía.

## 6. Prueba rápida

1. Escribe al WhatsApp Business conectado a Chatwoot.
2. Debe aparecer reply del bot en el hilo (1 mensaje, o 2–3 si el agente decide partir), con una pausa de 8–16 s.
3. Pide cotización con toneladas → debe crear lead.
4. Pide “hablar con un asesor” → conversación pasa a **open**; el bot **sigue** hasta que un asesor escriba.
5. Pide el catálogo / carta de presentación → el bot adjunta el PDF.

El bot deja una **nota privada** en el hilo. **Mirar o asignar no calla al bot;
escribir al cliente sí.** Para devolverle el hilo al bot, pon el ticket en
**Pending**. Un error puntual del LLM **no** abre el ticket; solo tras
`AGENT_ERROR_HANDOFF_THRESHOLD` fallos seguidos.

Horario laboral (orientativo, no es promesa): L–V 8:00–19:00 y sábados
9:00–13:00, Ciudad de México. Fuera de horario el agente no dice “en breve”.

En droplets de 1 GB el API corre con **1 worker** uvicorn. No subir
`--workers` sin una cola externa (Redis): debounce y contadores van en memoria.

## 7. Troubleshooting

| Síntoma | Causa típica |
|---------|----------------|
| Chatwoot: *error with the agent bot* + logs `401` en `/webhook/chatwoot` | Firma HMAC inválida. Chatwoot firma `HMAC(secret, "{timestamp}.{body}")` con `X-Chatwoot-Signature` + `X-Chatwoot-Timestamp`. Confirma que `CHATWOOT_WEBHOOK_SECRET` sea el **secret del bot** (no el access token). |
| Desbloqueo rápido | Vacía `CHATWOOT_WEBHOOK_SECRET=` en `.env`, recrea el contenedor `api`, vuelve a probar. Luego restaura el secret con un deploy que tenga la verificación correcta. |
| Bot no responde pero HTTP 200 | Un humano ya escribió en público (`chatwoot_skip_human_replied`), o el hilo está `resolved`/`snoozed`. Falta de API key. |
| Hilo `open` y el bot sigue hablando | Esperado hasta que un asesor escriba al cliente. Para callarlo: responder en público. Para devolverlo al bot: status **Pending**. |
| Adjunto / audio sin texto | El bot pide descripción por texto (`chatwoot_skip_empty_content` solo si no hay attachments). |
| RAG vacío / no respeta catálogo | Ver `/dashboard/knowledge` (FAQs activas, chunks > 0). Seed corre al arrancar si las tablas están vacías. Sin `OPENAI_API_KEY` no hay embeddings (solo keyword). |

## 8. Dependencias

```bash
pip install -r requirements.txt
# incluye openai-agents[litellm]
```

Docs SDK: [OpenAI Agents Python](https://github.com/openai/openai-agents-python) · LiteLLM multi-provider.
