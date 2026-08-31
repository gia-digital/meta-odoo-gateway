"""Utilidades de chunking sin dependencias del knowledge store."""
from __future__ import annotations

from typing import List

# ~800 tokens ≈ 3200 caracteres; overlap ~100 tokens
CHUNK_CHARS = 3200
CHUNK_OVERLAP = 400


def chunk_text(text: str, *, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> List[str]:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return []
    if len(cleaned) <= size:
        return [cleaned]
    chunks: List[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + size)
        chunks.append(cleaned[start:end].strip())
        if end >= len(cleaned):
            break
        start = max(0, end - overlap)
    return [c for c in chunks if c]
