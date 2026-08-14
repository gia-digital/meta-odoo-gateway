# Configuración de Odoo Enterprise

## 1. Crear usuario de integración

No uses el usuario admin para la integración. Crea un usuario dedicado:

1. Inicia sesión como admin en Odoo.
2. **Settings → Users & Companies → Users → Create**.
3. Datos:
   - Name: `Integración Gateway`
   - Email: `integrations@tuempresa.com`
   - Access Rights:
     - Sales: **Administrator** (para crear leads y asignar a cualquier vendedor)
     - Contacts: **Administrator**
     - Discuss: **Internal User**
4. Guarda.

## 2. Generar API Key

Odoo Enterprise permite API Keys que reemplazan el password — más seguro y revocable.

1. Inicia sesión como el usuario de integración (`integrations@...`).
2. Ve a **Preferences (avatar arriba) → Account Security → New API Key**.
3. Pon una descripción: `GIA Gateway production`.
4. Genera la key. **Cópiala inmediatamente** — solo se muestra una vez.
5. Pégala en `.env`:
   ```
   ODOO_API_KEY=tu_api_key_aqui
   ```

## 3. Identificar IDs necesarios

El gateway necesita IDs numéricos de Odoo. Para obtenerlos:

### Sales Team ID

1. **CRM → Configuration → Sales Teams**.
2. Abre el equipo deseado.
3. La URL tendrá: `/web#id=1&model=crm.team` → el `id=1` es el ID.
4. Cópialo a `ODOO_DEFAULT_SALES_TEAM_ID`.

### Salesperson (User) ID

1. **Settings → Users → Manage Users**.
2. Abre el usuario al que asignar leads por defecto.
3. URL: `/web#id=7&model=res.users` → `7` es el ID.
4. Cópialo a `ODOO_DEFAULT_SALESPERSON_ID`.

## 4. Verificar conectividad

Desde tu máquina, prueba la API con curl:

```bash
curl -X POST https://odoo.tuempresa.com/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "call",
    "params": {
      "service": "common",
      "method": "authenticate",
      "args": ["production", "integrations@tuempresa.com", "TU_API_KEY", {}]
    }
  }'
```

Respuesta esperada:
```json
{"jsonrpc": "2.0", "id": null, "result": 7}
```

(El número `7` es el uid del usuario — confirma que la autenticación funciona.)

## 5. Estructura del lead generado

Cuando el gateway crea un `crm.lead`, lo hace con esta estructura:

| Campo Odoo | Origen | Ejemplo |
|---|---|---|
| `name` | Canal + nombre o ID | `[WHATSAPP] Juan Pérez` |
| `type` | Fijo | `lead` |
| `contact_name` | Nombre del usuario | `Juan Pérez` |
| `phone` / `mobile` | WhatsApp ID o phone | `5215512345678` |
| `email_from` | Si el usuario lo compartió | `juan@example.com` |
| `description` | Historial de conversación (HTML) | Últimos 20 mensajes |
| `source_id` | utm.source = "Whatsapp" / "Messenger" | Auto-creado |
| `priority` | Según score | 1 (medium) / 2 (high) / 3 (very high) |
| `team_id` | Default configurado | Equipo de ventas asignado |
| `user_id` | Default configurado | Vendedor asignado |

Para leads "calientes" (score ≥ umbral de handoff), además se crea:

- **mail.activity** tipo "To Do" para el vendedor, con resumen de señales detectadas
- **mail.message** (nota interna) en el lead con la misma información

## 6. Configuración recomendada en CRM Odoo

Para aprovechar al máximo la integración:

### Etapas del pipeline

Asegúrate de tener al menos:
- **New** (donde caen los leads creados por el gateway)
- **Qualified** (cuando el vendedor valida)
- **Proposition** / **Won** / **Lost** según tu proceso

### Tags útiles

Crea tags como:
- `Meta-Inbound` — para identificar todos los leads que vinieron del gateway
- `Hot-Lead` — para handoffs prioritarios
- `WhatsApp` / `Messenger` — por canal

Estos IDs los puedes pasar en `tag_ids` al crear el lead (extensión futura).

### Reportes

En **CRM → Reporting → Pipeline Analysis** filtra por `Source = Whatsapp` o `Messenger` para medir el desempeño del canal automatizado.

## 7. Módulo opcional Odoo (alternativa)

Si prefieres una integración más profunda (sin gateway intermedio para Odoo), se puede desarrollar un módulo custom de Odoo que escuche directamente al webhook. Sin embargo, esto **acopla Chatwoot/el agente a Odoo** — el patrón con FastAPI intermedio es más mantenible porque:

- Aísla cambios del Agent Bot del core de Odoo
- Permite agregar más canales (Telegram, web chat, etc.) sin tocar Odoo
- Facilita testing y debugging independiente
- Mantiene Odoo enfocado en su rol de CRM, no de integrador

Recomendación: **mantener el patrón con FastAPI** salvo que haya restricciones organizacionales para correr otro servicio.

## 8. Backup y permisos

- El usuario de integración debe tener permisos limitados al mínimo necesario (CRM + Contacts).
- Roota la API Key después del onboarding inicial (renovar cada 6-12 meses).
- Si la key se compromete, revócala desde **Preferences → Account Security**.
