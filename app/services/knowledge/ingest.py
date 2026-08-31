"""Extracción de texto, chunking e indexado de archivos."""
from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.knowledge import KnowledgeFile
from app.services.knowledge.chunking import chunk_text
from app.services.knowledge.store import KnowledgeStore

logger = get_logger(__name__)


def uploads_dir() -> Path:
    settings = get_settings()
    path = Path(settings.knowledge_uploads_dir)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n\n".join(pages)
    raise ValueError(f"Formato no soportado: {suffix or path.name}")


def copy_into_uploads(src: Path, dest_name: str) -> Path:
    dest = uploads_dir() / dest_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


async def ingest_file(db: AsyncSession, file_row: KnowledgeFile) -> KnowledgeFile:
    store = KnowledgeStore(db)
    path = Path(file_row.stored_path)
    if not path.is_absolute():
        path = uploads_dir() / path.name
    try:
        raw = extract_text(path)
        chunks = chunk_text(raw)
        if not chunks:
            await store.mark_file_status(
                file_row, status="error", error="No se pudo extraer texto"
            )
            return file_row
        await store.replace_file_chunks(file_row, chunks)
        await store.mark_file_status(file_row, status="indexed", error=None)
        logger.info(
            "knowledge_file_indexed",
            file_id=file_row.id,
            chunks=len(chunks),
            filename=file_row.filename,
        )
    except Exception as exc:
        logger.exception("knowledge_file_ingest_failed", file_id=file_row.id, error=str(exc))
        await store.mark_file_status(file_row, status="error", error=str(exc)[:500])
    return file_row
