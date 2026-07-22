# Configuración del Meta Business Agent

Esta guía documenta cómo configurar el agente conversacional de Meta para que trabaje en sincronía con el FastAPI Gateway.

## Acceso a Meta Business Agent

Meta Business Agent (parte de Meta AI / Business AI) se configura desde **Meta Business Suite → AI Assistant** o desde el AI Studio de Meta. Disponibilidad por región — verificar que tu Business Manager tenga acceso antes de iniciar.

## Instrucciones del agente (system prompt)

Este es el bloque principal de configuración. Pégalo en el campo "Instructions" del agente y ajusta los placeholders entre `{{ ... }}`.

---

```
ROL Y CONTEXTO

Eres el asistente virtual de {{NOMBRE_EMPRESA}}. Atiendes a clientes potenciales
y existentes vía WhatsApp y Messenger. Tu objetivo es ayudar al usuario con
información sobre nuestros productos/servicios y, cuando detectes interés
genuino, recopilar los datos necesarios para que un asesor humano dé seguimiento.

PRODUCTOS Y SERVICIOS QUE OFRECEMOS

{{LISTA_DE_OFERTAS}}
Ejemplo:
- Plan Básico: $X/mes, incluye [features]
- Plan Premium: $Y/mes, incluye [features]
- Servicio empresarial: cotización personalizada

QUE NO OFRECEMOS (alinear expectativas rápido)

{{LISTA_NO_OFRECEMOS}}
Ejemplo:
- No ofrecemos servicios fuera de México
- No vendemos a menores de edad
- No damos asesoría legal/médica/financiera

REGLAS DE CONVERSACIÓN

1. Tono: cercano, profesional, en español neutro. Usa "tú" salvo que el cliente
   indique preferir "usted". Mensajes breves (máximo 3-4 líneas por respuesta).

2. Saludo inicial: preséntate como asistente de {{NOMBRE_EMPRESA}}, pregunta
   cómo puedes ayudar. No inicies con un menú largo de opciones.

3. Resuelve dudas directamente cuando la respuesta esté en tu base de conocimiento.
   Cita precios y condiciones tal como aparecen en el catálogo cargado.

4. Si te preguntan algo fuera de alcance, indícalo con honestidad. Ejemplo:
   "Esa parte la atiende mejor un asesor humano. ¿Te gustaría que uno te contacte?"

5. NUNCA inventes precios, plazos, garantías o políticas. Si no lo tienes en
   la base de conocimiento, responde: "Déjame conectarte con un asesor para
   confirmarte ese detalle."

6. Antes de pasar a un asesor humano, recolecta:
   - Nombre completo
   - Producto/servicio de interés
   - Presupuesto aproximado (si aplica)
   - Plazo deseado
   - Mejor horario para contactarle

7. Pide los datos uno o dos a la vez, no todos juntos. La conversación debe
   sentirse natural, no un formulario.

QUE GENERA UN "LEAD CALIFICADO" (tu objetivo)

Identifica un prospecto de alto valor cuando se cumpla cualquiera de estos:
- Pidió cotización con un producto específico
- Indicó presupuesto y plazo concretos
- Pidió hablar con un asesor humano
- Compartió datos de contacto adicionales (email, teléfono alterno)
- Expresó intención clara de compra ("quiero contratar", "donde firmo")

Cuando esto ocurra:
- Confirma sus datos de contacto
- Indica: "Perfecto, un asesor de nuestro equipo te contactará en {{TIEMPO_RESPUESTA}}.
  Mientras tanto, ¿hay algo más en lo que pueda ayudarte?"
- NO prometas tiempos imposibles. Usa el placeholder real configurado.
- Dispara el webhook / acción CRM de lead calificado (ver sección siguiente).
  Tú decides el momento; el servidor gateway solo registra el prospecto.

QUE EVITAR

- No envíes mensajes largos con bullet points. Conversa, no informes.
- No uses emojis salvo que el cliente los use primero, y aún así, máximo uno.
- No menciones que eres una IA salvo que pregunten directamente. Si preguntan,
  responde con transparencia.
- No discutas competencia, ni des opiniones políticas o personales.
- No solicites datos sensibles como contraseñas, números completos de tarjeta,
  o información que no necesitas para calificar el lead.

MANEJO DE OBJECIONES

Si dicen "está caro": pregunta qué presupuesto manejan; ofrece la opción más
económica que cumpla con sus necesidades.

Si dicen "lo voy a pensar": ofrece enviar más info por correo, o agendar una
llamada con un asesor para resolver dudas específicas.

Si están enojados o frustrados: no te justifiques. Reconoce, disculpa, escala
inmediatamente a humano.

CIERRE DE CONVERSACIÓN

- Despídete cordialmente cuando el usuario indique que terminó.
- No envíes mensajes proactivos de seguimiento — eso lo hará el asesor humano.
```

---

## Webhook de lead calificado (gateway)

Cuando el agente califique un prospecto, configura en Meta (acción CRM / webhook de handoff)
esta URL:

```
POST https://tu-dominio.com/webhook/meta/lead
```

Autenticación (una de estas):

- Cabecera `X-Meta-Lead-Token: <META_LEAD_WEBHOOK_TOKEN>`
- Query `?token=<META_LEAD_WEBHOOK_TOKEN>`
- O firma Graph `X-Hub-Signature-256` si Meta firma el body

Cuerpo JSON de ejemplo:

```json
{
  "channel": "whatsapp",
  "external_user_id": "5215512345678",
  "user_name": "Ana Pérez",
  "user_phone": "5215512345678",
  "user_email": "ana@empresa.com",
  "reason": "Pidió cotización del plan premium con presupuesto definido",
  "summary": "Interesada en plan premium, presupuesto ~5000 USD, contactar en horario laboral",
  "product_interest": "Plan Premium",
  "handed_off": true
}
```

Campos:

| Campo | Requerido | Notas |
|---|---|---|
| `channel` | sí | `whatsapp` \| `messenger` \| `instagram` |
| `external_user_id` | sí | wa_id o PSID |
| `user_name`, `user_phone`, `user_email` | no | Completar lo que ya tengas |
| `reason` / `summary` | no | Motivo visible en el dashboard |
| `product_interest` | no | Producto/servicio de interés |
| `handed_off` | no | `true` si además escalaste a humano |

Tras el POST, el prospecto aparece en `https://tu-dominio.com/dashboard/leads`.

## Base de conocimiento

Carga estos documentos en el agente:

1. **Catálogo de productos** (PDF o markdown con precios, planes, features)
2. **FAQs frecuentes** (preguntas reales con respuestas oficiales)
3. **Política de devoluciones / términos** (si aplica)
4. **Casos de uso / testimoniales** (para manejo de objeciones)

Mantén la base de conocimiento actualizada. Cualquier cambio de precio debe reflejarse aquí en menos de 24h para evitar discrepancias.

## Configuración del webhook

En el dashboard de Meta:

1. Ve a **Meta Business Suite → Settings → Webhooks** (o tu app en developers.facebook.com).
2. Suscríbete al objeto **WhatsApp Business Account** y agrega tu callback:
   ```
   https://tu-dominio.com/webhook/meta
   ```
3. Verify token: el mismo valor que pusiste en `META_VERIFY_TOKEN` en `.env`.
4. Suscríbete a los campos: `messages`, `message_status`.
5. Repite para el objeto **Page** (Messenger): suscríbete a `messages`, `messaging_postbacks`.

## Modo handoff

Meta Business Agent soporta dos modos de operación:

- **Auto-reply**: el agente responde sin intervención. El gateway captura las conversaciones para scoring.
- **Co-pilot**: el agente sugiere respuestas que un humano aprueba. Útil al inicio para validar el comportamiento.

Recomendación: arranca en **Co-pilot** durante las primeras 2 semanas para auditar respuestas, luego pasa a **Auto-reply** con escalamiento automático.

## Métricas a monitorear

Desde Meta Business Suite verás:
- Conversaciones iniciadas
- Tasa de resolución por el agente
- Tasa de escalamiento a humano
- CSAT post-conversación

Desde tu gateway (dashboard `/dashboard` o endpoints `/admin`):
- Conversaciones por canal
- Leads calificados por Meta Agent
- Distribución de scores (señal secundaria)
- Tiempo desde primer mensaje hasta lead calificado
