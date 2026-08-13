"""CRUD + reindex de chunks para el knowledge store."""
from __future__ import annotations

from typing import List, Optional, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.knowledge import (
    KnowledgeBusiness,
    KnowledgeChunk,
    KnowledgeFaq,
    KnowledgeFile,
    KnowledgeSkill,
)
from app.services.knowledge.embeddings import embed_texts

logger = get_logger(__name__)


class KnowledgeStore:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def stats(self) -> dict:
        async def _count(model, **filters) -> int:
            stmt = select(func.count()).select_from(model)
            for key, val in filters.items():
                stmt = stmt.where(getattr(model, key) == val)
            return int((await self.db.execute(stmt)).scalar() or 0)

        last_file = (
            await self.db.execute(
                select(KnowledgeFile.updated_at).order_by(KnowledgeFile.updated_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        last_faq = (
            await self.db.execute(
                select(KnowledgeFaq.updated_at).order_by(KnowledgeFaq.updated_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        last_skill = (
            await self.db.execute(
                select(KnowledgeSkill.updated_at)
                .order_by(KnowledgeSkill.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        last_biz = (
            await self.db.execute(select(KnowledgeBusiness.updated_at).limit(1))
        ).scalar_one_or_none()
        timestamps = [t for t in (last_file, last_faq, last_skill, last_biz) if t]
        return {
            "faqs_active": await _count(KnowledgeFaq, active=True),
            "faqs_total": await _count(KnowledgeFaq),
            "skills_active": await _count(KnowledgeSkill, active=True),
            "skills_total": await _count(KnowledgeSkill),
            "files_active": await _count(KnowledgeFile, active=True),
            "files_total": await _count(KnowledgeFile),
            "chunks": await _count(KnowledgeChunk),
            "last_updated": max(timestamps) if timestamps else None,
        }

    async def get_business(self) -> Optional[KnowledgeBusiness]:
        return (await self.db.execute(select(KnowledgeBusiness).limit(1))).scalar_one_or_none()

    async def upsert_business(self, **fields) -> KnowledgeBusiness:
        row = await self.get_business()
        if row is None:
            row = KnowledgeBusiness(**fields)
            self.db.add(row)
        else:
            for key, val in fields.items():
                setattr(row, key, val or "")
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def list_faqs(
        self, *, q: str = "", include_inactive: bool = True
    ) -> List[KnowledgeFaq]:
        stmt = select(KnowledgeFaq).order_by(KnowledgeFaq.id.asc())
        if not include_inactive:
            stmt = stmt.where(KnowledgeFaq.active.is_(True))
        if q.strip():
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                KnowledgeFaq.question.ilike(like) | KnowledgeFaq.answer.ilike(like)
            )
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_faq(self, faq_id: int) -> Optional[KnowledgeFaq]:
        return await self.db.get(KnowledgeFaq, faq_id)

    async def save_faq(self, faq: KnowledgeFaq) -> KnowledgeFaq:
        self.db.add(faq)
        await self.db.commit()
        await self.db.refresh(faq)
        await self.index_faq(faq)
        return faq

    async def list_skills(self, *, include_inactive: bool = True) -> List[KnowledgeSkill]:
        stmt = select(KnowledgeSkill).order_by(KnowledgeSkill.id.asc())
        if not include_inactive:
            stmt = stmt.where(KnowledgeSkill.active.is_(True))
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_skill(self, skill_id: int) -> Optional[KnowledgeSkill]:
        return await self.db.get(KnowledgeSkill, skill_id)

    async def save_skill(self, skill: KnowledgeSkill) -> KnowledgeSkill:
        self.db.add(skill)
        await self.db.commit()
        await self.db.refresh(skill)
        await self.index_skill(skill)
        return skill

    async def list_files(self) -> List[KnowledgeFile]:
        stmt = select(KnowledgeFile).order_by(KnowledgeFile.id.desc())
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_file(self, file_id: int) -> Optional[KnowledgeFile]:
        return await self.db.get(KnowledgeFile, file_id)

    async def save_file(self, file_row: KnowledgeFile) -> KnowledgeFile:
        self.db.add(file_row)
        await self.db.commit()
        await self.db.refresh(file_row)
        return file_row

    async def delete_file(self, file_row: KnowledgeFile) -> None:
        await self._delete_chunks("file", file_row.id)
        await self.db.delete(file_row)
        await self.db.commit()

    async def mark_file_status(
        self, file_row: KnowledgeFile, *, status: str, error: Optional[str]
    ) -> None:
        file_row.status = status
        file_row.error_message = error
        await self.db.commit()
        await self.db.refresh(file_row)

    async def index_faq(self, faq: KnowledgeFaq) -> None:
        await self._delete_chunks("faq", faq.id)
        if not faq.active:
            await self.db.commit()
            return
        text = f"P: {faq.question.strip()}\nR: {faq.answer.strip()}"
        await self._insert_chunks(
            source_type="faq",
            source_id=faq.id,
            title=(faq.question or "")[:255],
            texts=[text],
        )

    async def index_skill(self, skill: KnowledgeSkill) -> None:
        await self._delete_chunks("skill", skill.id)
        if not skill.active:
            await self.db.commit()
            return
        text = (
            f"{skill.title.strip()}\n"
            f"Cuando aplicar: {(skill.when_to_apply or '').strip()}\n"
            f"{(skill.body or '').strip()}"
        )
        await self._insert_chunks(
            source_type="skill",
            source_id=skill.id,
            title=(skill.title or "")[:255],
            texts=[text],
        )

    async def replace_file_chunks(self, file_row: KnowledgeFile, texts: Sequence[str]) -> None:
        await self._delete_chunks("file", file_row.id)
        await self._insert_chunks(
            source_type="file",
            source_id=file_row.id,
            title=(file_row.filename or "")[:255],
            texts=list(texts),
            file_id=file_row.id,
        )

    async def _delete_chunks(self, source_type: str, source_id: int) -> None:
        await self.db.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.source_type == source_type,
                KnowledgeChunk.source_id == source_id,
            )
        )

    async def _insert_chunks(
        self,
        *,
        source_type: str,
        source_id: int,
        title: str,
        texts: List[str],
        file_id: Optional[int] = None,
    ) -> None:
        vectors = await embed_texts(texts)
        for i, (text, vec) in enumerate(zip(texts, vectors)):
            self.db.add(
                KnowledgeChunk(
                    source_type=source_type,
                    source_id=source_id,
                    file_id=file_id,
                    chunk_index=i,
                    title=title,
                    text=text,
                    embedding=vec,
                )
            )
        await self.db.commit()
        logger.info(
            "knowledge_chunks_indexed",
            source_type=source_type,
            source_id=source_id,
            n=len(texts),
            embedded=sum(1 for v in vectors if v is not None),
        )
