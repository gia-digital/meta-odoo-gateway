# Connector Tools (GIA)

Docs: [connector-tools](https://developers.facebook.com/documentation/meta-business-agent/reference/configure/connector-tools)

Fuente editable: `agent_info/connector_tools.json`  
Conector padre: ver `agent_info/connectors.json`

## Live — `create_lead`

| Campo | Valor |
|-------|--------|
| `tool_id` | `pfbid02WTE5fxeCTAmRLLEuU22mTyPxmwuwbM6rHRsYNX6XrtsECCHQ8QxnXdyd2mDoSP8LwXL5GbM16sHS9UrSkcPRN1onxufrYPQDGrl` |
| name | `create_lead` |
| method/path | `POST /webhook/meta/lead` (alias de `POST /leads`) |
| auth usuario | `user_auth_required: false` (auth del conector: API key) |

Registro actual en Meta es **mínimo** (sin schema de body). El JSON del repo incluye la definición **enriquecida** (campos `LeadCreate`) para actualizar con PUT.

## Cómo actualizar

```bash
export META_GRAPH_TOKEN='...'
# opcional: META_CONNECTOR_ID=... META_TOOL_ID=...

./scripts/upload_meta_connector_tools.sh --dry-run
./scripts/upload_meta_connector_tools.sh --list
./scripts/upload_meta_connector_tools.sh --update   # PUT enrich create_lead (recomendado)
./scripts/upload_meta_connector_tools.sh --create   # solo si el tool no existe
./scripts/upload_meta_connector_tools.sh --run      # prueba dry execution vía Meta
```

Tras PUT, confirma que skills (`create-qualified-lead`) siguen nombrando el mismo `name`/`tool_id`.
