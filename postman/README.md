# Postman — Meta Business Agent (GIA)

Snapshot local + scripts paralelos del workspace **Grupo Industrial Acerero**.

Colección live: **Meta Business Agent** (`30548378-d2fa13ad-046e-4cd2-9a23-dcbce42d147d`)  
`entity_id` canónico (WA Phone Number ID): **`1247354378459524`**

## Inventario (fuente de verdad → API)

| Carpeta Postman | Fuente repo | Script | Docs Meta |
|-----------------|-------------|--------|-----------|
| Knowledge Files | `agent_info/*.pdf` | `scripts/upload_meta_knowledge.sh` | [files](https://developers.facebook.com/documentation/meta-business-agent/reference/configure/agent-knowledge-files) |
| Knowledge FAQs | `agent_info/faqs.json` | `scripts/upload_meta_faqs.sh` | [faqs](https://developers.facebook.com/documentation/meta-business-agent/reference/configure/agent-knowledge-faqs) |
| Knowledge Business Info | `agent_info/business_info.json` | `scripts/upload_meta_business_info.sh` | [business-info](https://developers.facebook.com/documentation/meta-business-agent/reference/configure/agent-knowledge-business-info) |
| Knowledge Skills | `agent_info/skills.json` | `scripts/upload_meta_skills.sh` | [skills](https://developers.facebook.com/documentation/meta-business-agent/reference/configure/agent-skills) |
| Knowledge Websites | `agent_info/websites.json` | `scripts/upload_meta_websites.sh` | [websites](https://developers.facebook.com/documentation/meta-business-agent/reference/configure/agent-knowledge-websites) |
| Connectors | `agent_info/connectors.json` | `scripts/upload_meta_connectors.sh` | [connectors](https://developers.facebook.com/documentation/meta-business-agent/reference/configure/connectors) |
| Connector Tools | `agent_info/connector_tools.json` | `scripts/upload_meta_connector_tools.sh` | [connector-tools](https://developers.facebook.com/documentation/meta-business-agent/reference/configure/connector-tools) |
| Agent Ops | — | — | eligibility / test |

Cada `agent_info/*.md` resume el mismo contenido para lectura humana.

## Variables de colección

| Variable | Uso |
|----------|-----|
| `bearer_token_1db5` | Token Meta Graph (secreto; no versionar valor) |
| `entity_id` | `1247354378459524` |
| `meta_lead_webhook_token` | Mismo valor que `META_LEAD_WEBHOOK_TOKEN` en `.env` |
| `connector_id` | Live `gia_lead_gateway` |
| `tool_id` | Live `create_lead` |
| `faq_id` / `knowledge_file_id` / `skill_id` / `website_id` | IDs de Create/List |

## Cómo actualizar (flujo recomendado)

1. Edita el JSON en `agent_info/` (no copies secrets reales).
2. `--dry-run` con el script correspondiente.
3. Ejecuta el script (batch) **o** el request Postman (one-off).
4. Si Meta devuelve un id nuevo (`connector_id`, `tool_id`, …), actualiza:
   - `agent_info/connectors.json` → `live.*`
   - `agent_info/connector_tools.json` → `live.*` / `connector_id`
   - variables Postman
   - referencias en `skills.json` (`create-qualified-lead`) si cambió el tool

### Websites

```bash
export META_GRAPH_TOKEN='...'
./scripts/upload_meta_websites.sh --dry-run
./scripts/upload_meta_websites.sh
./scripts/upload_meta_websites.sh --list
```

### Connectors

```bash
export META_GRAPH_TOKEN='...'
export META_LEAD_WEBHOOK_TOKEN='...'   # header X-Meta-Lead-Token
./scripts/upload_meta_connectors.sh --list
./scripts/upload_meta_connectors.sh --get
./scripts/upload_meta_connectors.sh --dry-run --update
./scripts/upload_meta_connectors.sh --upsert-key   # rotar token
```

### Tools (`create_lead`)

```bash
./scripts/upload_meta_connector_tools.sh --list
./scripts/upload_meta_connector_tools.sh --dry-run --update
./scripts/upload_meta_connector_tools.sh --update   # enriquecer schema body
./scripts/upload_meta_connector_tools.sh --run      # prueba vía Meta
```

Live actuales (confirmar con `--list` si se recrean):

- connector: `pfbid0Z8ZS1jWkQMPXtbJL8j6s1nALxS693Ai5nz2ZZC55JfdLwwDQ738QfjN4fnCczZtWnBRkV5ubondskFdSEbEWch8wDi65gXWRcKl`
- tool `create_lead`: `pfbid02WTE5fxeCTAmRLLEuU22mTyPxmwuwbM6rHRsYNX6XrtsECCHQ8QxnXdyd2mDoSP8LwXL5GbM16sHS9UrSkcPRN1onxufrYPQDGrl`
- path: `POST /webhook/meta/lead` (alias de `/leads` en el gateway)

## Otros scripts ya existentes

```bash
./scripts/upload_meta_faqs.sh --dry-run
./scripts/upload_meta_business_info.sh --dry-run
./scripts/upload_meta_skills.sh --dry-run
./scripts/upload_meta_knowledge.sh "agent_info/Presentación GIA.pdf" "Presentacion GIA.pdf"
```

## Importar snapshot

Archivo: `postman/collections/meta-business-agent.json` (Collection v2.1).  
Tras importar, rellena secretos en variables; no commits con tokens.
