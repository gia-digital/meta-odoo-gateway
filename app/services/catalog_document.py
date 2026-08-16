"""Localiza y envía la Carta de Presentación GIA (catálogo comercial).

WhatsApp/Chatwoot no cachean el PDF entre clientes: cada send_catalog vuelve
a subir el archivo. El mismo hilo ya lo tiene en el historial (no reenviar).
"""
from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.knowledge import KnowledgeFile
from app.services.knowledge.ingest import uploads_dir
from app.services.knowledge.store import KnowledgeStore

logger = get_logger(__name__)

CATALOG_FILENAME = "Carta Presentación GIA.pdf"
CATALOG_CAPTION = "Carta de presentación GIA"


def _norm(name: str) -> str:
    return unicodedata.normalize("NFC", name or "").casefold()


def is_catalog_filename(name: str) -> bool:
    """True solo para la carta comercial, no para la presentación corporativa 2027."""
    n = _norm(name)
    return "carta" in n and "present" in n and n.endswith(".pdf")


def agent_info_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "agent_info"


def resolve_catalog_path(stored_path: Optional[str] = None) -> Optional[Path]:
    candidates: list[Path] = []
    if stored_path:
        path = Path(stored_path)
        if not path.is_absolute():
            path = uploads_dir() / path.name
        candidates.append(path)
    uploads = uploads_dir()
    candidates.append(uploads / CATALOG_FILENAME)
    for existing in uploads.glob("*.pdf"):
        if is_catalog_filename(existing.name):
            candidates.append(existing)
    candidates.append(agent_info_dir() / CATALOG_FILENAME)
    for src in agent_info_dir().glob("*.pdf"):
        if is_catalog_filename(src.name):
            candidates.append(src)

    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path
    return None


async def find_catalog_file_row(db: AsyncSession) -> Optional[KnowledgeFile]:
    store = KnowledgeStore(db)
    active: Optional[KnowledgeFile] = None
    any_match: Optional[KnowledgeFile] = None
    for row in await store.list_files():
        if not is_catalog_filename(row.filename):
            continue
        if any_match is None:
            any_match = row
        if row.active:
            active = row
            break
    return active or any_match


async def find_catalog_pdf(db: AsyncSession) -> Optional[Path]:
    row = await find_catalog_file_row(db)
    stored = row.stored_path if row is not None else None
    path = resolve_catalog_path(stored)
    if path is None:
        logger.warning("catalog_pdf_not_found", stored_path=stored)
    return path


async def deliver_catalog(bot) -> str:
    """Envía el PDF al hilo de Chatwoot. `bot` es un BotContext."""
    if bot.extra.get("catalog_sent"):
        return (
            "El catálogo ya se envió en este turno. Confirma al cliente que lo "
            "tiene y pregunta qué material y tonelaje busca."
        )
    path = await find_catalog_pdf(bot.db)
    if path is None:
        return (
            "No se encontró el PDF de la carta de presentación. Describe las "
            "líneas del catálogo en texto (aceros planos, acanalados, tubería "
            "industrial, varilla y alambre) y ofrece que un asesor lo envíe."
        )

    from app.services.chatwoot_client import ChatwootClient, ChatwootError

    try:
        async with ChatwootClient() as cw:
            await cw.send_attachment(
                bot.chatwoot_conversation_id,
                path,
                content=CATALOG_CAPTION,
                filename=CATALOG_FILENAME,
            )
    except ChatwootError as exc:
        logger.error(
            "catalog_send_failed",
            error=str(exc),
            conversation_id=bot.chatwoot_conversation_id,
            path=str(path),
        )
        return (
            "No se pudo adjuntar el PDF en Chatwoot. Describe las líneas del "
            "catálogo en texto y ofrece que un asesor se lo envíe."
        )
    except Exception as exc:
        logger.exception(
            "catalog_send_failed",
            error=str(exc),
            conversation_id=bot.chatwoot_conversation_id,
        )
        return (
            "No se pudo adjuntar el PDF en Chatwoot. Describe las líneas del "
            "catálogo en texto y ofrece que un asesor se lo envíe."
        )

    bot.extra["catalog_sent"] = True
    logger.info(
        "catalog_sent",
        conversation_id=bot.chatwoot_conversation_id,
        path=str(path),
        bytes=path.stat().st_size,
    )
    return (
        "Catálogo enviado (Carta de presentación GIA.pdf). Confirma al cliente "
        "que ya lo tiene y pregunta qué material y tonelaje busca. No lo "
        "vuelvas a enviar en este turno. No es la lista de precios mensual."
    )
