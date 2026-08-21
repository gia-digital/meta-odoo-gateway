# agent_info — knowledge del agente GIA (Chatwoot)

Payloads versionados para el seed de Postgres + pgvector. El Agent Bot de Chatwoot los carga al primer boot (si las tablas están vacías) y se editan después en `/dashboard/knowledge`.

| Archivo | Uso |
|---------|-----|
| `faqs.json` | FAQs → `knowledge_faqs` |
| `business_info.json` | Perfil de negocio → `knowledge_business` |
| `products.json` | Catálogo y servicios → `knowledge_products` |
| `skills.json` | Skills del agente → `knowledge_skills` |
| `websites.json` | URLs de referencia |
| `*.pdf` | Presentaciones indexadas como files. `Carta Presentación GIA.pdf` también se envía al cliente con el tool `send_catalog`. |

**No se ingiere** `conversaciones_whatsapp.txt`. Ver [`docs/chatwoot_agent_bot.md`](../docs/chatwoot_agent_bot.md).

Guía operativa / tono: `Guia_Respuesta_GIA.docx`

## Reglas al actualizar

1. Edita el JSON (y el `.md` si el resumen cambia).
2. Skills con `source=seed`: al reiniciar el API se refrescan desde `skills.json`. Si las editas en `/dashboard/knowledge`, pasan a `source=manual` y ya no se sobrescriben.
3. FAQs/productos en un entorno ya seeded: aplica cambios en el dashboard (el seed no los sobrescribe).
4. No commits de secretos.
