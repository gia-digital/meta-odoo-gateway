"""API de leads: tool para Meta Business Agent + listado admin."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_token, require_meta_lead_auth
from app.models.conversation import Channel, Conversation, ConversationStatus
from app.models.db import get_db
from app.models.schemas import LeadCreate, LeadOut
from app.services.conversation import ConversationService

LEAD_STATUSES = (ConversationStatus.qualified, ConversationStatus.handed_off)

router = APIRouter(prefix="/leads", tags=["leads"])


def lead_to_out(conv: Conversation) -> LeadOut:
    return LeadOut(
        id=conv.id,
        channel=conv.channel.value,
        external_user_id=conv.external_user_id,
        user_name=conv.user_name,
        user_phone=conv.user_phone,
        user_email=conv.user_email,
        status=conv.status.value,
        qualification_source=conv.qualification_source.value,
        qualification_reason=conv.qualification_reason,
        product_interest=conv.product_interest,
        lead_summary=conv.lead_summary,
        budget=conv.budget,
        timeline=conv.timeline,
        preferred_contact_time=conv.preferred_contact_time,
        score=conv.score,
        qualified_at=conv.qualified_at,
        odoo_lead_id=conv.odoo_lead_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


async def create_lead_from_create(
    db: AsyncSession, payload: LeadCreate
) -> Conversation:
    try:
        channel_enum = Channel(payload.channel.lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid channel: {payload.channel}. Use whatsapp|messenger|instagram",
        ) from exc

    service = ConversationService(db)
    return await service.create_lead_from_payload(
        channel=channel_enum,
        external_user_id=payload.external_user_id,
        user_name=payload.user_name,
        user_phone=payload.user_phone,
        user_email=payload.user_email,
        reason=payload.reason,
        summary=payload.summary,
        product_interest=payload.product_interest,
        budget=payload.budget,
        timeline=payload.timeline,
        preferred_contact_time=payload.preferred_contact_time,
        handed_off=payload.handed_off,
    )


@router.post(
    "",
    response_model=LeadOut,
    status_code=200,
    summary="Crear o actualizar prospecto calificado",
    description=(
        "Tool para el agente de GIA: registra un prospecto de acero con "
        "material, volumen, entrega y datos de contacto para el equipo de ventas."
    ),
)
async def create_lead(
    body: bytes = Depends(require_meta_lead_auth),
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    import json

    try:
        raw = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    if isinstance(raw.get("lead"), dict):
        raw = raw["lead"]

    try:
        payload = LeadCreate.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid lead payload: {exc}") from exc

    conv = await create_lead_from_create(db, payload)
    return lead_to_out(conv)


@router.get(
    "",
    response_model=List[LeadOut],
    summary="Listar leads calificados",
    dependencies=[Depends(require_admin_token)],
)
async def list_leads(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    channel: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
) -> List[LeadOut]:
    stmt = (
        select(Conversation)
        .where(Conversation.status.in_(LEAD_STATUSES))
        .order_by(
            Conversation.qualified_at.desc().nullslast(),
            Conversation.updated_at.desc(),
        )
    )
    if channel:
        try:
            stmt = stmt.where(Conversation.channel == Channel(channel.lower()))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid channel: {channel}") from exc
    if status_filter:
        try:
            st = ConversationStatus(status_filter)
            if st not in LEAD_STATUSES:
                raise ValueError(status_filter)
            stmt = stmt.where(Conversation.status == st)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid status: {status_filter}"
            ) from exc

    result = await db.execute(stmt.limit(limit).offset(offset))
    return [lead_to_out(c) for c in result.scalars().all()]


@router.get(
    "/{lead_id}",
    response_model=LeadOut,
    summary="Detalle de un lead",
    dependencies=[Depends(require_admin_token)],
)
async def get_lead(lead_id: int, db: AsyncSession = Depends(get_db)) -> LeadOut:
    stmt = select(Conversation).where(Conversation.id == lead_id)
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv or conv.status not in LEAD_STATUSES:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead_to_out(conv)
