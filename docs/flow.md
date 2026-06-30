# Flujo de datos end-to-end

Este documento describe qué pasa, paso a paso, cuando un usuario envía un mensaje.

## Diagrama de secuencia

```
Cliente            Meta            Meta Business      FastAPI         Odoo
(WhatsApp)        Platform         Agent              Gateway         Enterprise
   |                |                 |                  |                |
   | Hola, busco    |                 |                  |                |
   | información    |                 |                  |                |
   |--------------->|                 |                  |                |
   |                | webhook event   |                  |                |
   |                |---------------->|                  |                |
   |                |                 | LLM genera resp. |                |
   |                |                 |                  |                |
   |                |                 | webhook copia    |                |
   |                |                 |----------------->|                |
   |                |                 |                  | Guarda msg     |
   |                |                 |                  | en DB local    |
   |                |                 |                  |                |
   |                |                 |                  | Calcula score  |
   |                |                 |                  | (score=3)      |
   |                |                 |                  |                |
   |                |                 |                  | No alcanza     |
   |                |                 |                  | umbral → wait  |
   |                |                 |                  |                |
   |                |  respuesta IA   |                  |                |
   |                |<----------------|                  |                |
   | Hola! Cómo te  |                 |                  |                |
   | puedo ayudar?  |                 |                  |                |
   |<---------------|                 |                  |                |
   |                |                 |                  |                |
   | Quiero el plan |                 |                  |                |
   | premium para   |                 |                  |                |
   | mi empresa,    |                 |                  |                |
   | presupuesto    |                 |                  |                |
   | $5000 USD      |                 |                  |                |
   |--------------->|                 |                  |                |
   |                |---------------->|                  |                |
   |                |                 |----------------->|                |
   |                |                 |                  | Score=7        |
   |                |                 |                  | (≥ 6)          |
   |                |                 |                  |                |
   |                |                 |                  | Buscar partner |
   |                |                 |                  |--------------->|
   |                |                 |                  |<---------------|
   |                |                 |                  | Crear partner  |
   |                |                 |                  |--------------->|
   |                |                 |                  |<---partner_id--|
   |                |                 |                  | Crear lead     |
   |                |                 |                  |--------------->|
   |                |                 |                  |<---lead_id-----|
   |                |                 |                  |                |
   | Respuesta IA   |                 |                  |                |
   | informativa    |                 |                  |                |
   |<---------------|<----------------|                  |                |
   |                |                 |                  |                |
   | Quiero hablar  |                 |                  |                |
   | con un asesor  |                 |                  |                |
   |--------------->|                 |                  |                |
   |                |---------------->|                  |                |
   |                |                 |----------------->|                |
   |                |                 |                  | Score=12       |
   |                |                 |                  | (≥ 9)          |
   |                |                 |                  |                |
   |                |                 |                  | Crear activity |
   |                |                 |                  | mail.activity  |
   |                |                 |                  |--------------->|
   |                |                 |                  | Nota interna   |
   |                |                 |                  |--------------->|
   |                |                 |                  |                |
   |                |                 |                  |                | Vendedor recibe
   |                |                 |                  |                | notificación
   |                |                 |                  |                | en Odoo
```

## Decisiones de diseño

### ¿Por qué guardar mensajes en la DB del gateway si Meta ya los guarda?

1. **Recálculo de score**: necesitamos el historial para reaplicar reglas si cambiamos la lógica.
2. **Auditoría**: trazabilidad de qué generó cada lead.
3. **Independencia de Meta**: si Meta cambia su API o tarda en responder consultas históricas, el gateway sigue funcionando.
4. **Latencia**: scoring local es < 10ms vs. consultar a Meta cada vez.

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

### ¿Qué pasa si llega un mensaje duplicado?

Meta puede reenviar webhooks (at-least-once delivery). El campo `external_message_id` es único: si llega un mensaje con el mismo ID, deberíamos detectarlo. Mejora pendiente: agregar un `UNIQUE INDEX` en `messages.external_message_id` y atrapar la excepción de integridad.

### ¿Y los mensajes no-texto (audio, imagen)?

Por ahora el gateway los ignora con un log. Roadmap:
- Audio: transcribir con Whisper, alimentar el scoring con el texto.
- Imagen: si es comprobante de pago, captura, etc., adjuntar al lead en Odoo.

## Variables que afectan el comportamiento

| Variable | Efecto |
|---|---|
| `LEAD_CREATION_THRESHOLD` | Score mínimo para crear lead automáticamente |
| `HUMAN_HANDOFF_THRESHOLD` | Score mínimo para crear actividad urgente al vendedor |
| `ODOO_DEFAULT_SALESPERSON_ID` | A quién se asignan los leads por defecto |
| Reglas en `lead_scorer.py` | Lista de criterios y puntos otorgados |
| Keywords en `lead_scorer.py` | Palabras clave para detectar productos, urgencia, etc. |

Recomendación: arrancar con los valores por defecto, monitorear primeras 50 conversaciones, ajustar umbrales y keywords con base en falsos positivos/negativos.
