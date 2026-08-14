# Roadmap y plan de implementación

## Timeline sugerido (6 semanas total)

### Semana 1 — Setup de infraestructura

- [ ] Aprovisionar servidor (cloud o on-prem) con Docker
- [ ] Configurar dominio + HTTPS (Caddy/Cloudflare Tunnel)
- [ ] Crear Agent Bot en Chatwoot y apuntar a `/webhook/chatwoot`
- [ ] Crear usuario de integración y API Key en Odoo (fase posterior)
- [ ] Clonar este repo, configurar `.env`, levantar con `docker compose up`

**Entregable**: gateway respondiendo healthchecks, bot conectado en Chatwoot.

### Semana 2 — Integración técnica

- [ ] Conectar inbox WhatsApp de Chatwoot al Agent Bot
- [ ] Validar que mensajes llegan al endpoint y se guardan en DB
- [ ] Verificar replies del agente y handoff a humano (`status=open`)
- [ ] Conectar Odoo (cuando aplique): primer lead desde `/admin/conversations/{id}/reprocess`

**Entregable**: flujo end-to-end funcionando con datos de prueba.

### Semana 3 — Configuración del agente IA

- [ ] Revisar knowledge en `/dashboard/knowledge` (catálogo, FAQs, precios)
- [ ] Iterar skills / instrucciones con casos reales
- [ ] Pruebas con 5-10 conversaciones simuladas internas
- [ ] Ajustar reglas y keywords del scorer según contexto del negocio
- [ ] Definir los productos/servicios específicos en `PRODUCT_KEYWORDS`

**Entregable**: agente respondiendo coherentemente, scoring calibrado.

### Semana 4 — Modo co-pilot (validación humana)

- [ ] Activar agente en modo co-pilot (humano aprueba antes de enviar)
- [ ] Lanzar a un grupo pequeño de clientes reales o staff
- [ ] Recolectar feedback de vendedores sobre la calidad de los leads
- [ ] Ajustar umbrales `LEAD_CREATION_THRESHOLD` y `HUMAN_HANDOFF_THRESHOLD`
- [ ] Refinar respuestas del agente con casos reales

**Entregable**: 30+ conversaciones procesadas, métricas de precision/recall en leads.

### Semana 5 — Lanzamiento producción

- [ ] Activar modo auto-reply
- [ ] Anunciar canal de WhatsApp a clientes
- [ ] Monitoreo intensivo (logs, leads creados, tiempos de respuesta)
- [ ] Setup de alertas (Sentry/Datadog para errores)
- [ ] Capacitar al equipo de ventas en el flujo de handoff desde Odoo

**Entregable**: sistema en producción atendiendo clientes reales.

### Semana 6 — Optimización y handover

- [ ] Análisis de primeras 100 conversaciones
- [ ] Identificar falsos positivos/negativos en leads
- [ ] Iterar reglas de scoring con datos reales
- [ ] Documentación final entregada al cliente
- [ ] Plan de mantenimiento mensual

**Entregable**: documentación de operación + plan de evolución.

---

## Estimación de costos mensuales

### Costos directos

| Concepto | Costo estimado |
|---|---|
| Servidor cloud (4GB RAM, 2 vCPU) | $20–40 USD |
| Dominio + SSL (Let's Encrypt gratis) | $1 USD |
| Backups y storage | $5–10 USD |
| **Total infraestructura** | **~$30–50 USD/mes** |

### Costos de canal / LLM

- **WhatsApp vía Chatwoot**: el cobro de conversaciones depende del proveedor del inbox (Cloud API u otro BSP).
- **LLM**: OpenAI / Anthropic según `AGENT_MODEL` y volumen de mensajes.
- **Chatwoot**: self-hosted o plan SaaS, según el despliegue.

### Costos de Odoo

Si ya tienes Odoo Enterprise self-hosted, el costo marginal de la integración es **$0** — usa la misma instancia, mismos usuarios.

---

## Consideraciones de seguridad

### Datos personales (LGPD/GDPR)

- El gateway guarda mensajes con datos personales (nombre, teléfono, email).
- **Política de retención sugerida**: borrar conversaciones cerradas después de 90 días si no resultaron en lead. Implementar como cron job.
- **Derecho al olvido**: agregar endpoint `/admin/conversations/{id}` con método DELETE.
- Documentar en aviso de privacidad que el chat es procesado por IA.

### Secretos

- `.env` **nunca** en el repo (incluido en `.gitignore`).
- API Keys rotadas cada 6-12 meses.
- Considerar Vault, AWS Secrets Manager o Doppler para producción seria.

### Auditoría

- Todos los eventos críticos se loggean (creación de lead, handoff, errores).
- Recomendado enviar logs a un sistema central (Loki, ELK, Datadog).

### Verificación de webhooks

El gateway valida `X-Chatwoot-Signature` cuando `CHATWOOT_WEBHOOK_SECRET` está definido. **Sin esta verificación**, cualquiera con tu URL podría inyectar mensajes falsos.

---

## Métricas a trackear

### De funnel (Odoo)

- Tasa de conversión: leads creados → ganados
- Tiempo de respuesta humano post-handoff
- Tasa de no-respuesta del prospecto

### De calidad del agente (Chatwoot)

- % de conversaciones resueltas sin handoff
- CSAT post-chat (si Chatwoot lo soporta)
- Tasa de abandono (usuarios que no responden tras N mensajes)

### Operativas (Gateway)

- Latencia del endpoint webhook (debe estar < 500ms p95)
- Errores 5xx (target: < 0.1%)
- Latencia de creación de lead en Odoo
- Distribución de scores (¿hay sesgo hacia umbral?)

---

## Extensiones futuras

### Corto plazo (1-3 meses post-lanzamiento)

- **Cola de retry persistente** para llamadas fallidas a Odoo
- **Idempotencia** en `external_message_id` (constraint UNIQUE)
- **Endpoint de reporting** con stats agregadas
- **Mensajes no-texto**: audio (transcripción) e imágenes (atajos al lead)

### Mediano plazo (3-6 meses)

- **Multi-tenant**: soportar múltiples cuentas de WhatsApp/Odoo en el mismo gateway
- **Templates de WhatsApp** para reactivar conversaciones fuera de la ventana de 24h
- **Integración con Calendar** (Odoo o Google) para que el agente agende reuniones
- **LLM secundario para clasificación**: usar Claude para detectar intención fina cuando las reglas no son suficientes

### Largo plazo (6-12 meses)

- **Multimodal**: el agente analiza imágenes (ej. cliente envía foto de producto)
- **Voice notes**: transcripción + respuesta en audio si el cliente prefiere
- **Personalización por segmento**: distintos system prompts para distintos productos
- **A/B testing** de respuestas del agente

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Chatwoot o el inbox WhatsApp cambia de API | El agente vive en el gateway; solo hay que adaptar `chatwoot_webhook` / `ChatwootClient` |
| Odoo upgrade rompe la API | Pin de versión de Odoo en producción, staging antes de upgrade |
| Crecimiento explosivo de mensajes | Migrar a workers async (Celery/Arq) + Redis para procesamiento desacoplado |
| Falsos positivos generan leads spam | Marcar como "junk" en Odoo + retroalimentar al scorer |
| Cliente no responde a 24h y se pierde contexto | Templates pre-aprobados de re-engagement |

---

## Quién hace qué

| Rol | Responsabilidades |
|---|---|
| Tech Lead | Arquitectura, integración, deploys |
| Marketing / Producto | Definir productos, FAQs, system prompt |
| Ventas | Validar calidad de leads, dar feedback al scorer |
| IT del cliente | Acceso a Odoo, dominio, infraestructura |
| Legal | Aviso de privacidad, términos del chat |
