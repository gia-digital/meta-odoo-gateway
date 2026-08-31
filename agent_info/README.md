# agent_info — knowledge del agente GIA (Chatwoot)

Payloads versionados para el seed de Postgres + pgvector. El Agent Bot de Chatwoot los carga al primer boot (si las tablas están vacías) y se editan después en `/dashboard/knowledge`.

| Archivo | Uso |
|---------|-----|
| `faqs.json` | FAQs → `knowledge_faqs` |
| `business_info.json` | Perfil de negocio → `knowledge_business` |
| `products.json` | Catálogo y servicios → `knowledge_products` |
| `product_specs.json` | Anexo A: calibres, espesores, pesos y rendimientos (se fusiona al importar/seed) |
| `skills.json` | Skills del agente → `knowledge_skills` |
| `websites.json` | URLs de referencia |
| `*.pdf` | Presentaciones indexadas como files. `Carta Presentación GIA.pdf` también se envía al cliente con el tool `send_catalog`. |

**No se ingiere** `conversaciones_whatsapp.txt`. Ver [`docs/chatwoot_agent_bot.md`](../docs/chatwoot_agent_bot.md).

Guía operativa / tono: `Guia_Respuesta_GIA.docx`

## Exportar (Postgres → repo)

1. **Dashboard:** Knowledge → Resumen → **Descargar knowledge (ZIP)**.
2. **CLI:**

```bash
docker compose -f docker-compose.prod.yml --env-file .deploy.env exec api \
  python -m scripts.export_knowledge --out /tmp/agent_info_export
```

## Importar (repo → Postgres)

Sobrescribe FAQs/skills/productos/negocio en vivo (no hace falta vaciar tablas).

1. **Dashboard:** Resumen → subir ZIP **o** marcar «Importar el agent_info/ del contenedor».
2. **CLI tras deploy:**

```bash
docker compose -f docker-compose.prod.yml --env-file .deploy.env exec api \
  python -m scripts.import_knowledge --from-agent-info
```

Opciones útiles: `--include-files`, `--deactivate-missing`.

## Reglas al actualizar

1. Edita el JSON (y el `.md` si el resumen cambia).
2. Skills con `source=seed`: al reiniciar el API se refrescan desde `skills.json`. Si las editas en `/dashboard/knowledge`, pasan a `source=manual` y ya no se sobrescriben — usa **import** para forzar el repo.
3. FAQs/productos: el seed de boot no sobrescribe; tras cambiar el repo usa **import** (dashboard o CLI).
4. No commits de secretos.
