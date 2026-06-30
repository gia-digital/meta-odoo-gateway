# Roadmap y plan de implementación

## Timeline sugerido (6 semanas total)

### Semana 1 — Setup de infraestructura

- [ ] Aprovisionar servidor (cloud o on-prem) con Docker
- [ ] Configurar dominio + HTTPS (Caddy/Cloudflare Tunnel)
- [ ] Crear Meta Developer App en modo desarrollo
- [ ] Verificar acceso a Meta Business Agent en la región del cliente
- [ ] Crear usuario de integración y API Key en Odoo
- [ ] Clonar este repo, configurar `.env`, levantar con `docker compose up`

**Entregable**: gateway respondiendo healthchecks, webhook verificado en Meta.

### Semana 2 — Integración técnica

- [ ] Conectar webhook real de WhatsApp en sandbox
- [ ] Validar que mensajes llegan al endpoint y se guardan en DB
- [ ] Conectar Odoo: crear primer lead manual desde `/admin/conversations/{id}/reprocess`
- [ ] Verificar formato del lead en Odoo, ajustar mapping si hace falta
- [ ] Configurar Messenger (página de Facebook)

**Entregable**: flujo end-to-end funcionando con datos de prueba.

### Semana 3 — Configuración del agente IA

- [ ] Cargar base de conocimiento en Meta Business Agent (catálogo, FAQs, precios)
- [ ] Iterar sobre el system prompt con casos reales
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
- [ ] Anunciar canal de WhatsApp/Messenger a clientes
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

### Costos de Meta

- **WhatsApp Cloud API**: las conversaciones se cobran por categoría (utility, marketing, service, authentication) y país. Service conversations iniciadas por el cliente son **gratis** las primeras 1000/mes; después varía entre $0.005 y $0.10 USD según país.
- **Messenger**: gratis para mensajería estándar dentro de la ventana de 24h.
- **Meta Business Agent**: actualmente Meta no cobra por uso del agente conversacional en sí (sujeto a cambios), pero las conversaciones de WhatsApp sí cuentan para el tarificador estándar.

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

El gateway valida `X-Hub-Signature-256` en cada request de Meta. **Sin esta verificación**, cualquiera con tu URL podría inyectar mensajes falsos y crear leads spam.

---

## Métricas a trackear

### De funnel (Odoo)

- Tasa de conversión: leads creados → ganados
- Tiempo de respuesta humano post-handoff
- Tasa de no-respuesta del prospecto

### De calidad del agente (Meta)

- % de conversaciones resueltas sin handoff
- CSAT post-chat (si Meta lo soporta)
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
| Meta deprecia o cambia Business Agent | El gateway puede operar con un LLM propio (Claude) llamado desde FastAPI sin cambiar el resto |
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
