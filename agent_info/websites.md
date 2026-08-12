# Knowledge Websites (GIA)

Docs: [agent-knowledge-websites](https://developers.facebook.com/documentation/meta-business-agent/reference/configure/agent-knowledge-websites)

Fuente editable: `agent_info/websites.json`

| URL | Propósito |
|-----|-----------|
| https://giacerero.com/ | Sitio corporativo |
| https://giacerero.com/terminos-y-condiciones | Términos / políticas |

## Cómo actualizar

1. Edita `websites.json`.
2. Dry-run: `./scripts/upload_meta_websites.sh --dry-run`
3. Sube nuevas URLs: `./scripts/upload_meta_websites.sh`
4. Lista / estado crawl: `./scripts/upload_meta_websites.sh --list`

Si una URL ya existe, el POST puede fallar o duplicar según Meta; usa List + Get por `website_id` y Delete/PUT según corresponda.
