# Postman — GIA Prospectos

El contrato HTTP del gateway está en [`specs/openapi.yaml`](specs/openapi.yaml).

Importa ese spec en Postman (o usa `/docs` de FastAPI) para probar:

| Recurso | Auth |
|---------|------|
| `POST /leads` | `X-Lead-Token` = `LEAD_WEBHOOK_TOKEN` |
| `GET /leads`, `GET /leads/{id}` | `X-Admin-Token` |
| `POST /webhook/chatwoot` | `X-Chatwoot-Signature` (+ timestamp) si hay `CHATWOOT_WEBHOOK_SECRET` |
| `/admin/conversations*` | `X-Admin-Token` |
| `/health` | ninguno |

El knowledge del agente se edita en `/dashboard/knowledge`; los JSON de `agent_info/` son el seed inicial. Ver [`agent_info/README.md`](../agent_info/README.md) y [`docs/chatwoot_agent_bot.md`](../docs/chatwoot_agent_bot.md).
