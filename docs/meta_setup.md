# Configuración de Meta — paso a paso

## 1. Crear la App en Meta for Developers

1. Ve a https://developers.facebook.com → **My Apps → Create App**.
2. Tipo: **Business**.
3. Asocia la app a tu **Business Manager** existente.

## 2. Configurar WhatsApp Business API

1. En el panel de tu app → **Add Product → WhatsApp**.
2. Selecciona el WABA (WhatsApp Business Account) ya verificado por el cliente.
3. Apunta el **Phone Number ID** que aparece en la pantalla → va al `.env` como `WHATSAPP_PHONE_NUMBER_ID`.
4. Genera un **System User Access Token** con permisos `whatsapp_business_messaging` y `whatsapp_business_management`:
   - **Business Settings → System Users → Generate Token**
   - Selecciona la app, expiración: **Never** (token de larga duración)
   - Cópialo a `META_ACCESS_TOKEN`.

## 3. Configurar Messenger

1. En el panel de tu app → **Add Product → Messenger**.
2. Conecta la página de Facebook del cliente.
3. Apunta el **Page ID** → va a `MESSENGER_PAGE_ID`.
4. El mismo System User Access Token sirve si tiene permisos `pages_messaging` y `pages_manage_metadata`.

## 4. Configurar el webhook

1. En la sección **Webhooks** de tu app:
   - Callback URL: `https://tu-dominio.com/webhook/meta`
   - Verify Token: lo que definiste en `META_VERIFY_TOKEN` (cualquier string seguro, mín. 32 chars)
2. Suscríbete al objeto **WhatsApp Business Account**:
   - Activa los campos: `messages`, `message_status` (y handovers si tu app los lista)
3. Suscríbete al objeto **Page** (Messenger):
   - Activa los campos: `messages`, `messaging_postbacks`, `message_deliveries`, `messaging_handovers` (si está disponible)
4. **App Secret**: en **Settings → Basic → App Secret** → cópialo a `META_APP_SECRET`. Esto se usa para verificar la firma `X-Hub-Signature-256` de cada webhook (crítico para seguridad).

## 5. Configurar Meta Business Agent

1. Desde **Meta Business Suite → AI Assistant** (o AI Studio), crea un nuevo agente.
2. Pega las instrucciones de `docs/agent_prompt.md`.
3. Sube la base de conocimiento (PDFs, FAQs, catálogo).
4. **Conecta el agente** al canal de WhatsApp y a la página de Messenger.
5. Webhooks del gateway:
   - Mensajes (Graph): `https://tu-dominio.com/webhook/meta`
   - **Lead calificado** (acción CRM / handoff del agente): `https://tu-dominio.com/webhook/meta/lead`
6. Define `META_LEAD_WEBHOOK_TOKEN` en `.env` y úsalo en la cabecera `X-Meta-Lead-Token` de la acción CRM.
7. Opcional: suscríbete a eventos de handover (`messaging_handovers` / thread control) en el webhook de mensajes; el gateway también los marca como lead.

Detalle del payload JSON: ver `docs/agent_prompt.md` (sección “Webhook de lead calificado”).

## 6. Verificar el flujo end-to-end

Una vez todo conectado:

```bash
# 1. Healthcheck del gateway
curl https://tu-dominio.com/health

# 2. Envía un mensaje de prueba a tu número de WhatsApp Business
# Desde Meta Business Suite → Test message

# 3. Revisa que el gateway haya recibido el evento
docker compose logs -f api | grep webhook_verified

# 4. Simula un lead calificado por Meta Agent
curl -X POST https://tu-dominio.com/webhook/meta/lead \
  -H "Content-Type: application/json" \
  -H "X-Meta-Lead-Token: tu_meta_lead_token" \
  -d '{
    "channel": "whatsapp",
    "external_user_id": "5215512345678",
    "user_name": "Prueba",
    "reason": "Lead de prueba",
    "handed_off": true
  }'

# 5. Revisa en el dashboard o en la API admin
# https://tu-dominio.com/dashboard/leads
curl -H "X-Admin-Token: tu_token_admin" \
     "https://tu-dominio.com/admin/conversations?status=qualified"
```

## 7. Limitaciones a tener en cuenta

- **Ventana de 24h en WhatsApp**: solo puedes responder gratis dentro de las 24h después del último mensaje del cliente. Fuera de eso necesitas usar **plantillas pre-aprobadas** (Message Templates).
- **Rate limits**: WhatsApp Cloud API tiene tiers (1K, 10K, 100K conversaciones/día). Solicita upgrade conforme el volumen crezca.
- **Disponibilidad de Meta Business Agent**: la disponibilidad regional cambia. Si tu cuenta aún no tiene acceso, puedes ejecutar la lógica conversacional con un LLM propio (Claude, GPT) llamando desde el gateway — el resto de la arquitectura no cambia.

## 8. Producción: HTTPS y dominio

Meta requiere que el webhook sea **HTTPS público con certificado válido**. Opciones:

- **Reverse proxy con Caddy o Traefik** (auto-HTTPS via Let's Encrypt). Ver `docs/nginx_caddy.md`.
- **Cloudflare Tunnel** si el gateway está en una red privada.
- **Nginx + certbot** para setup manual.

Nunca expongas el gateway sin HTTPS — Meta rechazará el webhook y los datos del cliente irían en claro.
