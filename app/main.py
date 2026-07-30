"""Entry point de la aplicación FastAPI."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.models.db import init_db
from app.routers import admin, dashboard, health, leads, meta_webhook

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await init_db()
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    debug=settings.app_debug,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(health.router)
app.include_router(meta_webhook.router)
app.include_router(leads.router)
app.include_router(admin.router)
app.include_router(dashboard.router)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": settings.app_name,
        "status": "running",
        "docs": "/docs",
        "dashboard": "/dashboard",
        "odoo_enabled": settings.odoo_enabled,
    }
