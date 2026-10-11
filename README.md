# GIA · Prospectos (Chatwoot → Gateway)

Servidor FastAPI para **Grupo Industrial Acerero**: hospeda el **agente de IA** (Agent Bot de Chatwoot / WhatsApp), guarda conversaciones y **prospectos calificados** en PostgreSQL, y los muestra en un dashboard interno. La sincronización con **Odoo** queda para una fase posterior (`ODOO_ENABLED=false` por defecto).

## Arquitectura (fase actual)

```
WhatsApp
        ↓
Chatwoot inbox (Agent Bot)
        ↓ POST /webhook/chatwoot
           FastAPI Gateway
        (agente GIA + persistencia + score secundario)
           ↓                    ↓
     Chatwoot reply      Dashboard HTML (/dashboard/leads)
```

## Stack

- Python 3.11 + FastAPI + Uvicorn
- Jinja2 (dashboard HTML)
- httpx (cliente async para Chatwoot y Odoo)
- SQLAlchemy + PostgreSQL + pgvector
- Pydantic v2
- Docker Compose

## Quick start

```bash
cp .env.example .env
# editar .env (mínimo: DATABASE_URL, ADMIN_API_TOKEN, CHATWOOT_*, OPENAI_API_KEY)

docker compose up -d
# API:        http://localhost:8000
# Dashboard:  http://localhost:8000/dashboard
# Docs:       http://localhost:8000/docs
```

## Endpoints clave

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/leads` | Crear/actualizar lead calificado (`X-Lead-Token`) |
| GET | `/leads` | Listar leads (cabecera `X-Admin-Token`) |
| GET | `/leads/{id}` | Detalle JSON de un lead |
| POST | `/webhook/chatwoot` | Agent Bot de Chatwoot (LLM + leads) |
| GET | `/dashboard/overview` | Resumen con KPIs y gráficos de prospectos |
| GET | `/dashboard` | Login del dashboard (token admin) |
| GET | `/dashboard/leads` | Lista de prospectos calificados |
| GET | `/dashboard/knowledge` | Knowledge RAG (instrucciones, FAQs, negocio, skills, files) |
| GET | `/health` | Health check |
| GET | `/admin/conversations` | API JSON (cabecera `X-Admin-Token`) |

## Flujo de leads

1. WhatsApp llega al inbox de Chatwoot; el Agent Bot llama a `POST /webhook/chatwoot`.
2. El agente GIA atiende con knowledge RAG y, cuando el prospecto está listo, usa el tool `create_lead`. Si piden el catálogo o la carta de presentación, usa `send_catalog` y adjunta el PDF.
3. El gateway marca la conversación como `qualified` / `handed_off` con `qualification_source=chatwoot_agent`.
4. Revisas el lead en `/dashboard/leads` antes de conectar Odoo.

El scoring local sigue calculándose (sección secundaria en el detalle) pero **no crea leads en Odoo** mientras `ODOO_ENABLED=false`.

## Configuración

- **Chatwoot Agent Bot:** `docs/chatwoot_agent_bot.md`
- Knowledge / RAG: `/dashboard/knowledge`
- Odoo (fase siguiente): `docs/odoo_setup.md`
- **Deploy DigitalOcean (CI/CD):** `docs/deploy.md`

## Migraciones de base de datos (Alembic)

Al arrancar, la API aplica las migraciones pendientes (`alembic upgrade head`) con un advisory lock de Postgres. Las bases creadas antes de Alembic se ponen al día con la migración base `0001`, que solo agrega lo que falte.

Para cambiar el esquema:

```bash
# 1. Edita los modelos en app/models/
# 2. Genera la migración contra la base local (ya migrada por `docker compose up`).
#    El -v monta el repo para que el archivo quede en migrations/versions/ del host.
docker compose build api
docker compose run --rm --no-deps -v "$PWD:/app" api \
  alembic revision --autogenerate -m "agregar campo x a conversations"
# 3. Revisa el archivo generado y pruébalo
docker compose run --rm --no-deps -v "$PWD:/app" api \
  sh -c "alembic upgrade head && alembic downgrade -1 && alembic upgrade head && alembic check"
```

CI falla si un modelo cambió sin migración (`alembic check`).

Reglas, porque el rollback automático regresa a la imagen anterior **sin** revertir la base:

- Solo agregar: columnas nullable o con `server_default`, tablas e índices nuevos.
- Para borrar o renombrar, hazlo en dos deploys: primero el código deja de usar la columna y después una migración la quita.

## CI/CD

| Workflow | Trigger | Acción |
|---|---|---|
| `CI` | PR → `main` | pytest + migraciones (`upgrade`, `check`, `downgrade`) contra pgvector + validación de `deploy/`, compose, Caddyfile e imagen |
| `Deploy` | push → `main` (o manual) | CI → imagen GHCR → SSH al droplet (respaldo, health, rollback) |
| `Droplet maintenance` | domingo 04:00 CDMX (o manual) | apt upgrade, imágenes base, limpieza Docker, respaldo de `knowledge_uploads`, reinicio si hace falta, verifica respaldos |

Respaldos de la base: antes de cada deploy y diarios (servicio `backup`). Restaurar con `deploy/restore.sh`.

Dependabot (`.github/dependabot.yml`) abre PRs los lunes para actions de GitHub, la imagen base de Python y las imágenes del compose (sin saltos de versión mayor de Postgres).

Imagen: `ghcr.io/gia-digital/meta-odoo-gateway:<sha>`

Producción incluye **Caddy** (HTTPS Let's Encrypt) delante de la API. Setup: [`docs/deploy.md`](docs/deploy.md).
