"""Entry point de la aplicación FastAPI."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.models.db import init_db
from app.routers import admin, health, meta_webhook


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await init_db()
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.app_debug,
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(meta_webhook.router)
app.include_router(admin.router)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": settings.app_name,
        "status": "running",
        "docs": "/docs",
    }
