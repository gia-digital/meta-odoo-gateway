# Flujo de datos end-to-end

Este documento describe qué pasa, paso a paso, cuando un usuario envía un mensaje.

**Fase actual:** WhatsApp llega a Chatwoot. El Agent Bot llama a `POST /webhook/chatwoot`; el agente GIA responde y califica leads con el tool `create_lead`. El scoring local es secundario. Odoo está desactivado (`ODOO_ENABLED=false`); los prospectos se revisan en `/dashboard/leads`.

## Diagrama de secuencia

```
Cliente            Chatwoot         FastAPI           Postgres
(WhatsApp)         inbox            Gateway           + RAG
   |                  |                |                 |
   | Hola, busco      |                |                 |
   | información      |                |                 |
   |----------------->|                |                 |
   |                  | POST           |                 |
   |                  | /webhook/      |                 |
   |                  | chatwoot       |                 |
   |                  |--------------->|                 |
   |                  |                | Guarda msg      |
   |                  |                |---------------->|
   |                  |                | Retrieval RAG   |
   |                  |                |<----------------|
   |                  |                | LLM (agente GIA)|
   |                  | reply          |                 |
   |                  |<---------------|                 |
   | Respuesta IA     |                |                 |
   |<-----------------|                |                 |
   |                  |                |                 |
   | Quiero cotizar   |                |                 |
   | lámina, 10 ton   |                |                 |
   |----------------->|--------------->|                 |
   |                  |                | tool create_lead|
   |                  |                | status=qualified|
   |                  |                |---------------->|
   |                  |                |                 |
   | Quiero hablar    |                |                 |
   | con un asesor    |                |                 |
   |----------------->|--------------->|                 |
   |                  |                | escalate +      |
   |                  | toggle_status  | handed_off      |
   |                  | open + nota    |                 |
   |                  |<---------------|                 |
   |                  |                | bot SIGUE       |
   |                  |                | hasta que un    |
   |                  |                | humano escriba  |
```

## Decisiones de diseño

### ¿Por qué guardar mensajes en la DB del gateway si Chatwoot ya los guarda?

1. **Contexto del agente**: el LLM usa los últimos `AGENT_MAX_HISTORY_MESSAGES` de la conversación local.
2. **Recálculo de score**: historial para reaplicar reglas si cambia la lógica.
3. **Auditoría**: trazabilidad de qué generó cada lead (detalle en `/dashboard/leads/{id}`).
4. **Latencia**: scoring local es < 10ms.

### ¿Por qué scoring por reglas y no LLM?

- **Determinismo**: el equipo de ventas necesita criterios claros y predecibles.
- **Costo**: cada mensaje pasaría por un LLM = costo lineal con volumen.
- **Velocidad**: regex y keywords son ~ms, LLM puede tardar segundos.
- **Auditabilidad**: cada señal disparada se registra con evidencia.

Si se requiere mayor sofisticación (detección de intención compleja, sentiment), se puede agregar un paso LLM **opcional** después del scoring por reglas, sin reemplazarlo.

### ¿Qué pasa si Odoo está caído?

El cliente `OdooClient` usa `tenacity` con backoff exponencial (3 reintentos). Si después de eso falla:
- El mensaje queda guardado en la DB del gateway.
- La conversación tiene su score calculado.
- En la próxima interacción se intentará crear el lead nuevamente.
- El endpoint `/admin/conversations/{id}/reprocess` permite forzar el reintento manualmente.

Mejora futura: cola de reintentos persistente (Redis + Arq, o tabla de "outbox").

### ¿Qué pasa si el gateway está caído cuando llega un mensaje?

El texto ya está en Chatwoot. El POST al bot no se reintenta si el puerto está cerrado (Chatwoot solo reintenta 429 y 500). Por eso el webhook se guarda en `webhook_inbox` y se hace commit **antes** de responder 200. Si el proceso muere a mitad del turno, al arrancar esa fila vuelve a `pending` y se procesa. Además, cada `CHATWOOT_RECONCILE_INTERVAL_SECONDS` se listan conversaciones `pending` y `open` de los últimos `CHATWOOT_RECONCILE_LOOKBACK_MINUTES` y se encolan los mensajes que nunca llegaron. Un apagón más largo que esa ventana no se responde solo.

### ¿Qué pasa si llega un mensaje duplicado?

Chatwoot (o reintentos de red) puede reenviar el mismo evento. `webhook_inbox.dedupe_key` (`msg:{id}` o `evt:conversation_resolved:{id}`) y el índice único parcial `messages.external_message_id` ignoran el duplicado. Un replay no vuelve a contestar si el bot ya escribió después de ese mensaje.

### ¿Y los mensajes no-texto (audio, imagen)?

Por ahora el gateway ignora contenido vacío. Roadmap:
- Audio: transcribir con Whisper, alimentar el scoring con el texto.
- Imagen: si es comprobante de pago, captura, etc., adjuntar al lead en Odoo.

## Variables que afectan el comportamiento

| Variable | Efecto |
|---|---|
| `LEAD_CREATION_THRESHOLD` | Score mínimo para crear lead automáticamente (si Odoo está on) |
| `HUMAN_HANDOFF_THRESHOLD` | Score mínimo para crear actividad urgente al vendedor |
| `ODOO_DEFAULT_SALESPERSON_ID` | A quién se asignan los leads por defecto |
| `AGENT_MAX_HISTORY_MESSAGES` | Ventana de historial que ve el agente |
| Reglas en `lead_scorer.py` | Lista de criterios y puntos otorgados |
| Keywords en `lead_scorer.py` | Palabras clave para detectar productos, urgencia, etc. |

Recomendación: arrancar con los valores por defecto, monitorear primeras 50 conversaciones, ajustar umbrales y keywords con base en falsos positivos/negativos.
