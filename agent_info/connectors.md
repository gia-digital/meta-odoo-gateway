# Connectors (GIA)

Docs: [connectors](https://developers.facebook.com/documentation/meta-business-agent/reference/configure/connectors)

Fuente editable: `agent_info/connectors.json`

## Live

| Campo | Valor |
|-------|--------|
| `connector_id` | `pfbid0Z8ZS1jWkQMPXtbJL8j6s1nALxS693Ai5nz2ZZC55JfdLwwDQ738QfjN4fnCczZtWnBRkV5ubondskFdSEbEWch8wDi65gXWRcKl` |
| name | `gia_lead_gateway` |
| base_url | `https://gia.init.com.mx` |
| auth | `API_KEY` header `X-Meta-Lead-Token` |

## Cómo actualizar

**Crear (solo si no existe):**

```bash
export META_GRAPH_TOKEN='...'
export META_LEAD_WEBHOOK_TOKEN='...'   # mismo que .env
./scripts/upload_meta_connectors.sh --dry-run
./scripts/upload_meta_connectors.sh --create
# guarda el id devuelto en connectors.json → live.connector_id y Postman {{connector_id}}
```

**Rotar API key (sin borrar el conector):**

```bash
./scripts/upload_meta_connectors.sh --upsert-key
```

**Actualizar nombre/descripción/base_url (PUT):**

```bash
./scripts/upload_meta_connectors.sh --update
```

**Inspeccionar:**

```bash
./scripts/upload_meta_connectors.sh --list
./scripts/upload_meta_connectors.sh --get
./scripts/upload_meta_connectors.sh --logs
```

No subas el valor real del token a git ni al body versionado: usa placeholders `{{META_LEAD_WEBHOOK_TOKEN}}` / `{{meta_lead_webhook_token}}`.
