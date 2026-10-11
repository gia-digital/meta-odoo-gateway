"""Health check endpoint (healthcheck de Docker, deploy y smoke tests)."""
import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.logging import get_logger
from app.models.db import engine

router = APIRouter(tags=["health"])
logger = get_logger(__name__)

DB_TIMEOUT_SECONDS = 3

# Con la base colgada (sin respuesta TCP), cancelar el ping no basta: el cierre de la
# conexión también se queda esperando. El ping corre aparte y solo hay uno en curso,
# así los healthchecks no se apilan ni agotan el pool.
_probe: asyncio.Task | None = None


async def _ping_db() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


def _consume_result(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


@router.get("/health")
async def health_check() -> JSONResponse:
    global _probe
    if _probe is None or _probe.done():
        _probe = asyncio.create_task(_ping_db())
        _probe.add_done_callback(_consume_result)

    done, _ = await asyncio.wait({_probe}, timeout=DB_TIMEOUT_SECONDS)
    if not done:
        error = f"sin respuesta en {DB_TIMEOUT_SECONDS}s"
    elif _probe.cancelled():
        error = "cancelado"
    else:
        exc = _probe.exception()
        error = (str(exc) or type(exc).__name__) if exc else None

    if error:
        logger.warning("health_db_unreachable", error=error)
        return JSONResponse({"status": "error", "database": "unreachable"}, status_code=503)
    return JSONResponse({"status": "ok", "database": "ok"})
