# Meta → Odoo Lead Gateway

Servidor intermedio (FastAPI) que conecta **Meta Business Agent** (WhatsApp / Messenger) con **Odoo Enterprise CRM** para automatizar la calificación y registro de leads.

## Arquitectura

```
WhatsApp / Messenger
        ↓
Meta Business Agent (IA conversacional)
        ↓ webhook
FastAPI Gateway  ← lógica de scoring y orquestación
        ↓ JSON-RPC
Odoo Enterprise CRM (crm.lead, res.partner, mail.message)
        ↓
Notificación a agente humano (cuando aplica)
```

## Stack

- Python 3.11 + FastAPI + Uvicorn
- httpx (cliente async para Meta y Odoo)
- SQLAlchemy + PostgreSQL (persistencia de conversaciones)
- Pydantic v2 (validación)
- Docker Compose para despliegue

## Estructura

```
app/
├── main.py                  # Entry point FastAPI
├── core/
│   ├── config.py            # Settings (env vars)
│   ├── security.py          # Verificación de firma Meta
│   └── logging.py           # Logging estructurado
├── routers/
│   ├── meta_webhook.py      # Endpoints Meta (verify + receive)
│   ├── health.py            # Health check
│   └── admin.py             # Admin (reprocessar, estadísticas)
├── services/
│   ├── meta_client.py       # Cliente WhatsApp/Messenger Graph API
│   ├── odoo_client.py       # Cliente JSON-RPC Odoo
│   ├── lead_scorer.py       # Lógica de scoring
│   └── conversation.py      # Manejo del estado de conversación
├── models/
│   ├── db.py                # SQLAlchemy base
│   ├── conversation.py      # Modelo Conversation, Message
│   └── schemas.py           # Pydantic schemas
└── tests/
    ├── test_scorer.py
    └── test_odoo_client.py
```

## Quick start

```bash
cp .env.example .env
# editar .env con credenciales

docker compose up -d
# servidor disponible en http://localhost:8000
# docs interactivos en http://localhost:8000/docs
```

## Endpoints clave

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/webhook/meta` | Verificación inicial del webhook (Meta) |
| POST | `/webhook/meta` | Recepción de mensajes y eventos de Meta |
| GET | `/health` | Estado del servicio |
| GET | `/admin/conversations` | Lista de conversaciones (auth requerida) |
| POST | `/admin/conversations/{id}/reprocess` | Reprocessar scoring de una conversación |

## Configuración de Meta

Ver `docs/meta_setup.md` para el paso a paso.

## Configuración de Odoo

Ver `docs/odoo_setup.md` — incluye creación de API key y módulo opcional.

## Flujo del agente

Ver `docs/agent_prompt.md` — instrucciones completas para configurar el Meta Business Agent.
