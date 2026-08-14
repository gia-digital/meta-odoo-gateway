"""Retrieval híbrido: pgvector cosine + keyword ILIKE."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.knowledge import KnowledgeChunk, KnowledgeFaq, KnowledgeFile, KnowledgeProduct, KnowledgeSkill
from app.services.knowledge.embeddings import embed_one

logger = get_logger(__name__)


@dataclass
class RetrievedHit:
    source_type: str
    source_id: int
    title: str
    text: str
    score: float


def format_hits(hits: Sequence[RetrievedHit]) -> str:
    if not hits:
        return ""
    lines = ["CONOCIMIENTO RECUPERADO (úsalo; no contradigas las políticas duras):"]
    for i, hit in enumerate(hits, start=1):
        label = {
            "faq": "FAQ",
            "skill": "Skill",
            "file": "Archivo",
            "product": "Producto",
        }.get(hit.source_type, hit.source_type)
        title = hit.title.strip() or f"{label} #{hit.source_id}"
        body = hit.text.strip()
        if len(body) > 1200:
            body = body[:1199].rstrip() + "…"
        lines.append(f"[{i}] {label}: {title}\n{body}")
    return "\n\n".join(lines)


async def retrieve_knowledge(
    db: AsyncSession, query: str, *, k: Optional[int] = None
) -> List[RetrievedHit]:
    settings = get_settings()
    limit = k or settings.knowledge_retrieve_k
    q = (query or "").strip()
    if not q:
        return []

    merged: dict[tuple[str, int, int], RetrievedHit] = {}

    vec = await embed_one(q)
    if vec is not None:
        stmt = (
            select(KnowledgeChunk)
            .where(KnowledgeChunk.embedding.isnot(None))
            .order_by(KnowledgeChunk.embedding.cosine_distance(vec))
            .limit(limit * 2)
        )
        rows = list((await db.execute(stmt)).scalars().all())
        await _filter_active(db, rows, merged, base_score=1.0)

    tokens = [t for t in _keywords(q) if len(t) >= 4][:6]
    if tokens:
        likes = [KnowledgeChunk.text.ilike(f"%{t}%") for t in tokens]
        likes.append(KnowledgeChunk.title.ilike(f"%{q[:80]}%"))
        stmt_kw = select(KnowledgeChunk).where(or_(*likes)).limit(limit * 2)
        rows_kw = list((await db.execute(stmt_kw)).scalars().all())
        await _filter_active(db, rows_kw, merged, base_score=0.35)

    hits = sorted(merged.values(), key=lambda h: h.score, reverse=True)[:limit]
    logger.info(
        "knowledge_retrieved",
        query_len=len(q),
        hits=len(hits),
        vector=vec is not None,
    )
    return hits


def _keywords(query: str) -> List[str]:
    raw = query.lower().replace("¿", " ").replace("?", " ")
    return [p.strip() for p in raw.replace(",", " ").split() if p.strip()]


async def _filter_active(
    db: AsyncSession,
    rows: Sequence[KnowledgeChunk],
    merged: dict,
    *,
    base_score: float,
) -> None:
    faq_ids = {r.source_id for r in rows if r.source_type == "faq"}
    skill_ids = {r.source_id for r in rows if r.source_type == "skill"}
    file_ids = {r.source_id for r in rows if r.source_type == "file"}
    product_ids = {r.source_id for r in rows if r.source_type == "product"}

    active_faqs = set()
    active_skills = set()
    active_files = set()
    active_products = set()
    if faq_ids:
        active_faqs = set(
            (
                await db.execute(
                    select(KnowledgeFaq.id).where(
                        KnowledgeFaq.id.in_(faq_ids), KnowledgeFaq.active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
    if skill_ids:
        active_skills = set(
            (
                await db.execute(
                    select(KnowledgeSkill.id).where(
                        KnowledgeSkill.id.in_(skill_ids), KnowledgeSkill.active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
    if file_ids:
        active_files = set(
            (
                await db.execute(
                    select(KnowledgeFile.id).where(
                        KnowledgeFile.id.in_(file_ids), KnowledgeFile.active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
    if product_ids:
        active_products = set(
            (
                await db.execute(
                    select(KnowledgeProduct.id).where(
                        KnowledgeProduct.id.in_(product_ids),
                        KnowledgeProduct.active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )

    for i, row in enumerate(rows):
        if row.source_type == "faq" and row.source_id not in active_faqs:
            continue
        if row.source_type == "skill" and row.source_id not in active_skills:
            continue
        if row.source_type == "file" and row.source_id not in active_files:
            continue
        if row.source_type == "product" and row.source_id not in active_products:
            continue
        key = (row.source_type, row.source_id, row.chunk_index)
        score = base_score - (i * 0.02)
        existing = merged.get(key)
        if existing is None or score > existing.score:
            merged[key] = RetrievedHit(
                source_type=row.source_type,
                source_id=row.source_id,
                title=row.title or "",
                text=row.text,
                score=score,
            )
