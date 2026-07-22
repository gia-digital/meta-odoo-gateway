"""Endpoints de administración: listar conversaciones, reprocesar scoring."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import require_admin_token
from app.models.conversation import Conversation, ConversationStatus, QualificationSource
from app.models.db import get_db
from app.models.schemas import ConversationOut, MessageOut
from app.services.conversation import ConversationService

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/conversations", response_model=List[ConversationOut])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    qualification_source: Optional[str] = Query(default=None),
):
    stmt = select(Conversation).order_by(Conversation.created_at.desc())
    if status_filter:
        try:
            stmt = stmt.where(Conversation.status == ConversationStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid status: {status_filter}")
    if qualification_source:
        try:
            stmt = stmt.where(
                Conversation.qualification_source
                == QualificationSource(qualification_source)
            )
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid qualification_source: {qualification_source}",
            )
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/conversations/{conv_id}/messages", response_model=List[MessageOut])
async def get_messages(conv_id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Conversation)
        .where(Conversation.id == conv_id)
        .options(selectinload(Conversation.messages))
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return sorted(conv.messages, key=lambda m: m.created_at)


@router.post("/conversations/{conv_id}/reprocess")
async def reprocess_conversation(conv_id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Conversation)
        .where(Conversation.id == conv_id)
        .options(selectinload(Conversation.messages))
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    service = ConversationService(db)
    await service.process_after_message(conv)
    return {
        "status": "reprocessed",
        "score": conv.score,
        "odoo_lead_id": conv.odoo_lead_id,
        "conversation_status": conv.status.value,
        "qualification_source": conv.qualification_source.value,
    }
