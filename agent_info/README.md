# agent_info — configuración Meta Business Agent (GIA)

Payloads versionados para knowledge, connectors y tools.  
**Postman** = inspección / one-off. **Scripts** = batch reproducible.

| Archivo | API Meta | Script |
|---------|----------|--------|
| `faqs.json` | `agent_config/faq` | `../scripts/upload_meta_faqs.sh` |
| `business_info.json` | `agent_config/business_info` | `../scripts/upload_meta_business_info.sh` |
| `skills.json` | `agent_config/skills` | `../scripts/upload_meta_skills.sh` |
| `websites.json` | `agent_config/websites` | `../scripts/upload_meta_websites.sh` |
| `connectors.json` | `agent_connectors` | `../scripts/upload_meta_connectors.sh` |
| `connector_tools.json` | `agent_connectors/{id}/tools` | `../scripts/upload_meta_connector_tools.sh` |
| `*.pdf` | `agent_config/files` | `../scripts/upload_meta_knowledge.sh` |

**Chatwoot Agent Bot** (sin Captain / sin Meta BA): el gateway carga `docs/agent_prompt.md` + skills/business_info/faqs vía OpenAI Agents SDK. Ver `../docs/chatwoot_agent_bot.md`.

Guía operativa / tono: `Guia_Respuesta_GIA.docx`  
Índice Postman: `../postman/README.md`

## Reglas al actualizar

1. Edita el JSON (y el `.md` si el resumen cambia).
2. Dry-run del script.
3. Sube / PUT.
4. Si Meta crea un **id nuevo**, propaga a `live.*`, variables Postman y skills que mencionen el tool.
5. Nunca commits de `META_GRAPH_TOKEN` ni `META_LEAD_WEBHOOK_TOKEN` reales — placeholders `{{...}}`.
