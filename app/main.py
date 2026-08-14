"""Entry point de la aplicación FastAPI."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.models.db import SessionLocal, init_db
from app.routers import admin, chatwoot_webhook, dashboard, health, knowledge as knowledge_router, leads
from app.services.knowledge.seed import seed_from_agent_info

STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await init_db()

    async def _seed() -> None:
        try:
            async with SessionLocal() as db:
                await seed_from_agent_info(db)
        except Exception as exc:
            logger.exception("knowledge_seed_failed", error=str(exc))

    # No bloquear /health: el seed (embeddings + PDFs) puede tardar minutos.
    seed_task = asyncio.create_task(_seed())
    yield
    seed_task.cancel()
    try:
        await seed_task
    except asyncio.CancelledError:
        pass


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    debug=settings.app_debug,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(health.router)
app.include_router(chatwoot_webhook.router)
app.include_router(leads.router)
app.include_router(admin.router)
app.include_router(dashboard.router)
app.include_router(knowledge_router.router)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": settings.app_name,
        "status": "running",
        "docs": "/docs",
        "dashboard": "/dashboard",
        "odoo_enabled": settings.odoo_enabled,
        "chatwoot_enabled": settings.chatwoot_enabled,
    }
