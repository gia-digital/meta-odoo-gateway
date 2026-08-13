"""Embeddings OpenAI para pgvector."""
from __future__ import annotations

from typing import List, Optional, Sequence

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_BATCH = 64


async def embed_texts(texts: Sequence[str]) -> List[Optional[List[float]]]:
    """Devuelve un vector por texto. None si no hay API key o el texto está vacío."""
    settings = get_settings()
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        logger.warning("knowledge_embed_skipped", reason="missing_openai_api_key")
        return [None] * len(texts)

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    model = settings.openai_embedding_model
    out: List[Optional[List[float]]] = [None] * len(texts)
    pending: List[tuple[int, str]] = [
        (i, t.strip()) for i, t in enumerate(texts) if t and t.strip()
    ]
    for start in range(0, len(pending), _BATCH):
        batch = pending[start : start + _BATCH]
        payload = [t for _, t in batch]
        try:
            resp = await client.embeddings.create(model=model, input=payload)
            for (idx, _), item in zip(batch, resp.data):
                out[idx] = list(item.embedding)
        except Exception as exc:
            logger.error("knowledge_embed_failed", error=str(exc), batch_size=len(batch))
            for idx, _ in batch:
                out[idx] = None
    return out


async def embed_one(text: str) -> Optional[List[float]]:
    vectors = await embed_texts([text])
    return vectors[0] if vectors else None
