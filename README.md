# GIA · Prospectos (Meta → Gateway)

Servidor intermedio (FastAPI) para **Grupo Industrial Acerero**: recibe conversaciones y **prospectos calificados** del Meta Business Agent (WhatsApp / Messenger), los guarda en PostgreSQL y los muestra en un dashboard interno. La sincronización con **Odoo** queda para una fase posterior (`ODOO_ENABLED=false` por defecto).

## Arquitectura (fase actual)

```
WhatsApp / Messenger
        ↓
Meta Business Agent (IA conversacional)
        ↓ mensajes          ↓ tool lead
POST /webhook/meta         POST /leads
        ↓                       ↓
           FastAPI Gateway
        (persistencia + score secundario)
                ↓
         Dashboard HTML (/dashboard/leads)
```

## Stack

- Python 3.11 + FastAPI + Uvicorn
- Jinja2 (dashboard HTML)
- httpx (cliente async para Meta y Odoo)
- SQLAlchemy + PostgreSQL
- Pydantic v2
- Docker Compose

## Quick start

```bash
cp .env.example .env
# editar .env (mínimo: META_*, META_LEAD_WEBHOOK_TOKEN, ADMIN_API_TOKEN, DATABASE_URL)

docker compose up -d
# API:        http://localhost:8000
# Dashboard:  http://localhost:8000/dashboard
# Docs:       http://localhost:8000/docs
```

## Endpoints clave

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/leads` | Tool del agente: crear/actualizar lead calificado |
| GET | `/leads` | Listar leads (cabecera `X-Admin-Token`) |
| GET | `/leads/{id}` | Detalle JSON de un lead |
| GET | `/webhook/meta` | Verificación del webhook (Meta) |
| POST | `/webhook/meta` | Mensajes + handovers de Meta |
| POST | `/webhook/meta/lead` | Alias legacy de `POST /leads` |
| GET | `/dashboard/overview` | Resumen con KPIs y gráficos de prospectos |
| GET | `/dashboard` | Login del dashboard (token admin) |
| GET | `/dashboard/leads` | Lista de prospectos calificados |
| GET | `/health` | Health check |
| GET | `/admin/conversations` | API JSON (cabecera `X-Admin-Token`) |

## Flujo de leads

1. El agente de Meta atiende la conversación.
2. Cuando el prospecto está listo, llama al tool `POST /leads` con producto, presupuesto, plazo, etc.
3. El gateway marca la conversación como `qualified` / `handed_off` con `qualification_source=meta_agent`.
4. Revisas el lead en `/dashboard/leads` antes de conectar Odoo.

El scoring local sigue calculándose (sección secundaria en el detalle) pero **no crea leads en Odoo** mientras `ODOO_ENABLED=false`.

## Configuración

- Meta: `docs/meta_setup.md`
- Prompt del agente + payload de lead: `docs/agent_prompt.md`
- Odoo (fase siguiente): `docs/odoo_setup.md`
- **Deploy DigitalOcean (CI/CD):** `docs/deploy.md`

## CI/CD

| Workflow | Trigger | Acción |
|---|---|---|
| `CI` | push/PR → `main` | pytest |
| `Deploy` | push → `main` (o manual) | test → imagen GHCR → SSH al droplet |

Imagen: `ghcr.io/gia-digital/meta-odoo-gateway:<sha>`

Producción incluye **Caddy** (HTTPS Let's Encrypt) delante de la API. Setup: [`docs/deploy.md`](docs/deploy.md).
