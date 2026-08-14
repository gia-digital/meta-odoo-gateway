"""Seed inicial desde agent_info/ (no sobrescribe ediciones manuales)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.knowledge import KnowledgeBusiness, KnowledgeFaq, KnowledgeFile, KnowledgeSkill
from app.services.knowledge.ingest import copy_into_uploads, ingest_file
from app.services.knowledge.store import KnowledgeStore

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[3]
AGENT_INFO = ROOT / "agent_info"

SEED_PDFS = (
    "Carta Presentación GIA.pdf",
    "Presentación GIA.pdf",
    "Presentación GIA.pdf",
)


def faq_question(item: Dict[str, Any]) -> str:
    q = item.get("question")
    if isinstance(q, str) and q.strip():
        return q.strip()
    questions = item.get("questions") or []
    if questions:
        return str(questions[0]).strip()
    return ""


async def seed_from_agent_info(db: AsyncSession, *, agent_info: Path | None = None) -> dict:
    """Carga JSON + PDFs si las tablas están vacías. Idempotente."""
    base = agent_info or AGENT_INFO
    store = KnowledgeStore(db)
    result = {"business": False, "faqs": 0, "skills": 0, "files": 0}

    try:
        await db.execute(text("SELECT pg_advisory_lock(872364)"))
    except Exception:
        pass

    try:
        biz_count = (
            await db.execute(select(func.count()).select_from(KnowledgeBusiness))
        ).scalar() or 0
        if biz_count == 0:
            from app.services.agent_knowledge import DEFAULT_AGENT_INSTRUCTIONS

            bi_path = base / "business_info.json"
            if bi_path.exists():
                data = json.loads(bi_path.read_text(encoding="utf-8"))
                payload = data.get("payload") or data
                contact = payload.get("contact_info") or {}
                await store.upsert_business(
                    business_description=payload.get("business_description") or "",
                    purchase_info=payload.get("purchase_info") or "",
                    payment_method=payload.get("payment_method") or "",
                    delivery_and_shipping=payload.get("delivery_and_shipping") or "",
                    return_policy=payload.get("return_policy") or "",
                    email=contact.get("email") or "",
                    hours_of_operation=contact.get("hours_of_operation") or "",
                    address=contact.get("address") or "",
                    agent_instructions=DEFAULT_AGENT_INSTRUCTIONS,
                )
                result["business"] = True
        else:
            row = await store.get_business()
            if row is not None and not (getattr(row, "agent_instructions", None) or "").strip():
                from app.services.agent_knowledge import DEFAULT_AGENT_INSTRUCTIONS

                row.agent_instructions = DEFAULT_AGENT_INSTRUCTIONS
                await db.commit()
                logger.info("knowledge_seed_backfill_agent_instructions")

        faq_count = (
            await db.execute(select(func.count()).select_from(KnowledgeFaq))
        ).scalar() or 0
        if faq_count == 0:
            faqs_path = base / "faqs.json"
            if faqs_path.exists():
                data = json.loads(faqs_path.read_text(encoding="utf-8"))
                for item in data.get("faqs") or []:
                    question = faq_question(item)
                    answer = (item.get("answer") or "").strip()
                    if not question or not answer:
                        continue
                    meta = item.get("metadata") or {}
                    faq = KnowledgeFaq(
                        question=question,
                        answer=answer,
                        category=str(meta.get("category") or ""),
                        active=True,
                        source="seed",
                    )
                    db.add(faq)
                    await db.flush()
                    await store.index_faq(faq)
                    result["faqs"] += 1

        skill_count = (
            await db.execute(select(func.count()).select_from(KnowledgeSkill))
        ).scalar() or 0
        if skill_count == 0:
            skills_path = base / "skills.json"
            if skills_path.exists():
                data = json.loads(skills_path.read_text(encoding="utf-8"))
                for item in data.get("skills") or []:
                    title = (item.get("title") or "").strip()
                    if not title:
                        continue
                    skill = KnowledgeSkill(
                        title=title,
                        when_to_apply=(item.get("description") or "").strip(),
                        body=(item.get("skill") or "").strip(),
                        active=True,
                        source="seed",
                    )
                    db.add(skill)
                    await db.flush()
                    await store.index_skill(skill)
                    result["skills"] += 1

        file_count = (
            await db.execute(select(func.count()).select_from(KnowledgeFile))
        ).scalar() or 0
        if file_count == 0 and base.exists():
            seen_names: set[str] = set()
            for name in SEED_PDFS:
                src = base / name
                if not src.exists():
                    continue
                dest_name = src.name
                if dest_name in seen_names:
                    continue
                seen_names.add(dest_name)
                try:
                    dest = copy_into_uploads(src, dest_name)
                except OSError as exc:
                    logger.error(
                        "knowledge_seed_pdf_copy_failed",
                        filename=dest_name,
                        error=str(exc),
                    )
                    continue
                file_row = KnowledgeFile(
                    filename=dest_name,
                    stored_path=str(dest),
                    mime="application/pdf",
                    byte_size=dest.stat().st_size,
                    status="pending",
                    active=True,
                    source="seed",
                )
                await store.save_file(file_row)
                await ingest_file(db, file_row)
                result["files"] += 1
    finally:
        try:
            await db.execute(text("SELECT pg_advisory_unlock(872364)"))
        except Exception:
            pass

    logger.info("knowledge_seed_done", **result)
    return result
