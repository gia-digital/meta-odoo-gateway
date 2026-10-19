"""
Servicio de orquestación de conversaciones.

Une:
- Persistencia (Conversation, Message)
- Scoring local (señal secundaria)
- Calificación por el agente GIA (Chatwoot)
- Creación de leads en Odoo (solo si ODOO_ENABLED=true)
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.db import commit_with_retry, is_deadlock
from app.models.conversation import (
    Channel,
    Conversation,
    ConversationStatus,
    Direction,
    Message,
    QualificationSource,
)
from app.models.schemas import NormalizedMessage, OdooLeadCreate
from app.services.lead_scorer import score_conversation
from app.services.odoo_client import OdooClient

logger = get_logger(__name__)

_OPEN_STATUSES = (
    ConversationStatus.active,
    ConversationStatus.qualified,
    ConversationStatus.handed_off,
)


def decide_inbound_cycle(
    *,
    resolved_at: Optional[datetime],
    payload_status: str,
    now: datetime,
    reopen_hours: float,
) -> str:
    """continue: mismo pedido. reopen: aclaración dentro de la ventana. new: pedido nuevo."""
    status = (payload_status or "").lower()
    if resolved_at is None:
        if status == "resolved":
            return "new"
        return "continue"
    closed = resolved_at
    if closed.tzinfo is None:
        closed = closed.replace(tzinfo=timezone.utc)
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    window = timedelta(hours=float(reopen_hours))
    if current - closed < window:
        return "reopen"
    return "new"


def cycle_private_note(resolved_at: datetime) -> str:
    """Nota interna de Chatwoot al abrir un pedido nuevo. El cliente no la ve."""
    settings = get_settings()
    try:
        tz = ZoneInfo(settings.display_timezone or "UTC")
    except Exception:
        tz = timezone.utc
    closed = resolved_at
    if closed.tzinfo is None:
        closed = closed.replace(tzinfo=timezone.utc)
    local = closed.astimezone(tz)
    return (
        f"Ciclo anterior cerrado el {local:%d/%m/%Y %H:%M}. "
        "Este mensaje se atiende como pedido nuevo."
    )


class ConversationService:
    """Orquesta el ciclo de vida de una conversación."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _latest_cycle(
        self,
        channel: Channel,
        external_user_id: str,
        *,
        include_resolved: bool,
    ) -> Optional[Conversation]:
        stmt = (
            select(Conversation)
            .where(
                Conversation.channel == channel,
                Conversation.external_user_id == external_user_id,
                Conversation.status.in_(_OPEN_STATUSES),
            )
            .options(selectinload(Conversation.messages))
            .order_by(Conversation.created_at.desc())
        )
        if not include_resolved:
            stmt = stmt.where(Conversation.resolved_at.is_(None))
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def _create_conversation(
        self,
        *,
        channel: Channel,
        external_user_id: str,
        user_name: Optional[str] = None,
        user_phone: Optional[str] = None,
        user_email: Optional[str] = None,
        chatwoot_conversation_id: Optional[int] = None,
    ) -> Conversation:
        conv = Conversation(
            channel=channel,
            external_user_id=external_user_id,
            user_name=user_name,
            user_phone=user_phone,
            user_email=user_email,
            status=ConversationStatus.active,
            qualification_source=QualificationSource.none,
            chatwoot_conversation_id=chatwoot_conversation_id,
            score=0,
            score_breakdown={},
        )
        self.db.add(conv)
        await commit_with_retry(self.db)
        await self.db.refresh(conv, ["messages"])
        logger.info("conversation_created", id=conv.id, channel=channel.value)
        return conv

    async def get_or_create(
        self,
        channel: Channel,
        external_user_id: str,
        user_name: Optional[str] = None,
        *,
        user_phone: Optional[str] = None,
        user_email: Optional[str] = None,
        create: bool = True,
        apply_cycle: bool = False,
        payload_status: str = "",
        chatwoot_conversation_id: Optional[int] = None,
    ) -> Optional[Conversation]:
        if apply_cycle:
            return await self._open_inbound_cycle(
                channel=channel,
                external_user_id=external_user_id,
                user_name=user_name,
                user_phone=user_phone,
                user_email=user_email,
                payload_status=payload_status,
                chatwoot_conversation_id=chatwoot_conversation_id,
            )

        conv = await self._latest_cycle(
            channel, external_user_id, include_resolved=False
        )
        if conv:
            return conv
        if not create:
            return None
        return await self._create_conversation(
            channel=channel,
            external_user_id=external_user_id,
            user_name=user_name,
            user_phone=user_phone,
            user_email=user_email,
            chatwoot_conversation_id=chatwoot_conversation_id,
        )

    async def _open_inbound_cycle(
        self,
        *,
        channel: Channel,
        external_user_id: str,
        user_name: Optional[str],
        user_phone: Optional[str],
        user_email: Optional[str],
        payload_status: str,
        chatwoot_conversation_id: Optional[int],
    ) -> Conversation:
        """Elige si el mensaje sigue el pedido abierto, lo reabre (<24h) o empieza otro."""
        now = datetime.now(timezone.utc)
        latest = await self._latest_cycle(
            channel, external_user_id, include_resolved=True
        )
        action = decide_inbound_cycle(
            resolved_at=latest.resolved_at if latest is not None else None,
            payload_status=payload_status,
            now=now,
            reopen_hours=get_settings().chatwoot_cycle_reopen_hours,
        )

        if latest is None:
            conv = await self._create_conversation(
                channel=channel,
                external_user_id=external_user_id,
                user_name=user_name,
                user_phone=user_phone,
                user_email=user_email,
                chatwoot_conversation_id=chatwoot_conversation_id,
            )
            conv.fresh_cycle = False
            conv.previous_resolved_at = None
            return conv

        if action == "continue":
            await self._touch_chatwoot_id(latest, chatwoot_conversation_id)
            latest.fresh_cycle = False
            latest.previous_resolved_at = None
            return latest

        if action == "reopen":
            latest.resolved_at = None
            if chatwoot_conversation_id:
                latest.chatwoot_conversation_id = chatwoot_conversation_id
            await commit_with_retry(self.db)
            await self.db.refresh(latest, ["messages"])
            latest.fresh_cycle = False
            latest.previous_resolved_at = None
            logger.info("cycle_reopened", conversation_id=latest.id)
            return latest

        closed_at = latest.resolved_at or now
        if latest.resolved_at is None:
            latest.resolved_at = closed_at
            if chatwoot_conversation_id:
                latest.chatwoot_conversation_id = chatwoot_conversation_id
            await commit_with_retry(self.db)
        conv = await self._create_conversation(
            channel=channel,
            external_user_id=external_user_id,
            user_name=user_name or latest.user_name,
            user_phone=user_phone or latest.user_phone,
            user_email=user_email or latest.user_email,
            chatwoot_conversation_id=chatwoot_conversation_id,
        )
        conv.fresh_cycle = True
        conv.previous_resolved_at = closed_at
        logger.info(
            "cycle_started",
            conversation_id=conv.id,
            previous_id=latest.id,
        )
        return conv

    async def _touch_chatwoot_id(
        self, conversation: Conversation, chatwoot_conversation_id: Optional[int]
    ) -> None:
        if not chatwoot_conversation_id:
            return
        if conversation.chatwoot_conversation_id == chatwoot_conversation_id:
            return
        conversation.chatwoot_conversation_id = chatwoot_conversation_id
        await commit_with_retry(self.db)
        await self.db.refresh(conversation, ["messages"])

    async def mark_cycle_resolved(
        self,
        *,
        channel: Channel,
        external_user_id: str,
        chatwoot_conversation_id: Optional[int] = None,
    ) -> Optional[Conversation]:
        """Cierra el ciclo comercial vigente. No cambia el status del lead."""
        conv = await self._latest_cycle(
            channel, external_user_id, include_resolved=False
        )
        if conv is None:
            logger.info(
                "cycle_resolve_no_open_conversation",
                external_user_id=external_user_id,
                chatwoot_conversation_id=chatwoot_conversation_id,
            )
            return None
        if conv.resolved_at is None:
            conv.resolved_at = datetime.now(timezone.utc)
        if chatwoot_conversation_id:
            conv.chatwoot_conversation_id = chatwoot_conversation_id
        await commit_with_retry(self.db)
        await self.db.refresh(conv)
        logger.info(
            "cycle_resolved",
            conversation_id=conv.id,
            chatwoot_conversation_id=chatwoot_conversation_id,
            status=conv.status.value,
        )
        return conv

    async def _inbound_by_external_id(
        self, external_message_id: str
    ) -> Optional[Message]:
        return await self.db.scalar(
            select(Message)
            .where(Message.external_message_id == external_message_id)
            .order_by(Message.id)
            .limit(1)
        )

    async def add_inbound_message(
        self, conversation: Conversation, message: NormalizedMessage
    ) -> Message:
        ext_id = message.external_message_id
        if ext_id:
            existing = await self._inbound_by_external_id(ext_id)
            if existing is not None:
                await self.db.refresh(conversation, ["messages"])
                return existing
        msg = Message(
            conversation_id=conversation.id,
            direction=Direction.inbound,
            body=message.text,
            external_message_id=ext_id,
            raw_payload=message.raw,
        )
        self.db.add(msg)

        if message.user_name and not conversation.user_name:
            conversation.user_name = message.user_name
        if message.user_phone and not conversation.user_phone:
            conversation.user_phone = message.user_phone

        try:
            await commit_with_retry(self.db)
        except IntegrityError:
            await self.db.rollback()
            if not ext_id:
                raise
            existing = await self._inbound_by_external_id(ext_id)
            if existing is None:
                raise
            await self.db.refresh(conversation, ["messages"])
            return existing
        await self.db.refresh(conversation, ["messages"])
        return msg

    async def process_after_message(self, conversation: Conversation) -> None:
        """
        Después de cada mensaje del usuario:
        1. Recalcular score (señal secundaria para el dashboard)
        2. Si Odoo está habilitado y umbrales lo permiten → sincronizar (fase 2)
        """
        score_result = score_conversation(conversation.messages)
        conversation.score = score_result.total
        conversation.score_breakdown = {
            "signals": [s.model_dump() for s in score_result.signals]
        }

        settings = get_settings()
        if settings.odoo_enabled:
            if score_result.create_lead and conversation.odoo_lead_id is None:
                await self._create_lead_in_odoo(conversation)
                if conversation.status == ConversationStatus.active:
                    conversation.status = ConversationStatus.qualified
                    if conversation.qualification_source == QualificationSource.none:
                        conversation.qualification_source = QualificationSource.local_score
                        conversation.qualified_at = datetime.now(timezone.utc)

            if score_result.notify_human and conversation.odoo_lead_id:
                await self._handoff_to_human(conversation)

        await commit_with_retry(self.db)

    async def qualify_lead(
        self,
        conversation: Conversation,
        *,
        reason: Optional[str] = None,
        user_name: Optional[str] = None,
        user_phone: Optional[str] = None,
        user_email: Optional[str] = None,
        handed_off: bool = False,
        product_interest: Optional[str] = None,
        summary: Optional[str] = None,
        budget: Optional[str] = None,
        timeline: Optional[str] = None,
        preferred_contact_time: Optional[str] = None,
        metadata: Optional[dict] = None,
        qualification_source: QualificationSource = QualificationSource.chatwoot_agent,
    ) -> Conversation:
        """
        Califica un prospecto (Chatwoot Agent Bot u otra fuente).
        No llama a Odoo (fase posterior).
        """
        if user_name:
            conversation.user_name = user_name
        if user_phone:
            conversation.user_phone = user_phone
        if user_email:
            conversation.user_email = user_email

        meta = metadata or {}
        interest = product_interest or meta.get("product_interest")
        lead_summary = summary or meta.get("summary")
        lead_budget = budget or meta.get("budget")
        lead_timeline = timeline or meta.get("timeline")
        lead_contact_time = preferred_contact_time or meta.get(
            "preferred_contact_time"
        )

        if interest:
            conversation.product_interest = str(interest)
        if lead_summary:
            conversation.lead_summary = str(lead_summary)
        if lead_budget:
            conversation.budget = str(lead_budget)
        if lead_timeline:
            conversation.timeline = str(lead_timeline)
        if lead_contact_time:
            conversation.preferred_contact_time = str(lead_contact_time)

        conversation.qualification_source = qualification_source
        if qualification_source == QualificationSource.chatwoot_agent:
            default_reason = "Qualified by Chatwoot Agent Bot"
        elif qualification_source == QualificationSource.local_score:
            default_reason = "Qualified by local score"
        else:
            default_reason = "Qualified lead"
        conversation.qualification_reason = reason or default_reason
        if conversation.qualified_at is None:
            conversation.qualified_at = datetime.now(timezone.utc)

        if handed_off:
            conversation.status = ConversationStatus.handed_off
            if getattr(conversation, "handed_off_at", None) is None:
                conversation.handed_off_at = datetime.now(timezone.utc)
        elif conversation.status == ConversationStatus.active:
            conversation.status = ConversationStatus.qualified

        # Recalcular score para contexto en dashboard
        if conversation.messages:
            score_result = score_conversation(conversation.messages)
            conversation.score = score_result.total
            conversation.score_breakdown = {
                "signals": [s.model_dump() for s in score_result.signals]
            }

        await commit_with_retry(self.db)
        await self.db.refresh(conversation)

        logger.info(
            "lead_qualified",
            conversation_id=conversation.id,
            status=conversation.status.value,
            handed_off=handed_off,
            source=qualification_source.value,
            product_interest=conversation.product_interest,
        )
        return conversation

    async def create_lead_from_payload(
        self,
        *,
        channel: Channel,
        external_user_id: str,
        user_name: Optional[str] = None,
        user_phone: Optional[str] = None,
        user_email: Optional[str] = None,
        reason: Optional[str] = None,
        summary: Optional[str] = None,
        product_interest: Optional[str] = None,
        budget: Optional[str] = None,
        timeline: Optional[str] = None,
        preferred_contact_time: Optional[str] = None,
        handed_off: bool = False,
        qualification_source: QualificationSource = QualificationSource.chatwoot_agent,
    ) -> Conversation:
        """Alta de lead vía tool del agente Chatwoot o POST /leads."""
        conv = await self.get_or_create(
            channel=channel,
            external_user_id=external_user_id,
            user_name=user_name,
        )
        phone = user_phone
        if not phone and channel == Channel.whatsapp:
            phone = external_user_id

        if qualification_source == QualificationSource.chatwoot_agent:
            default_reason = "Qualified by Chatwoot Agent Bot"
        elif qualification_source == QualificationSource.local_score:
            default_reason = "Qualified by local score"
        else:
            default_reason = "Qualified lead"
        return await self.qualify_lead(
            conv,
            reason=reason or summary or default_reason,
            user_name=user_name,
            user_phone=phone,
            user_email=user_email,
            handed_off=handed_off,
            product_interest=product_interest,
            summary=summary,
            budget=budget,
            timeline=timeline,
            preferred_contact_time=preferred_contact_time,
            qualification_source=qualification_source,
        )

    async def add_outbound_message(
        self,
        conversation: Conversation,
        body: str,
        *,
        external_message_id: Optional[str] = None,
        raw: Optional[dict] = None,
    ) -> Message:
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            msg = Message(
                conversation_id=conversation.id,
                direction=Direction.outbound,
                body=body,
                external_message_id=external_message_id,
                raw_payload=raw or {},
            )
            self.db.add(msg)
            try:
                await self.db.commit()
                await self.db.refresh(conversation, ["messages"])
                return msg
            except Exception as exc:
                last_exc = exc
                await self.db.rollback()
                if is_deadlock(exc) and attempt < 2:
                    logger.warning(
                        "outbound_deadlock_retry",
                        conversation_id=conversation.id,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                raise
        if last_exc:
            raise last_exc
        raise RuntimeError("add_outbound_message failed")

    async def mark_handed_off(
        self, conversation: Conversation, *, reason: Optional[str] = None
    ) -> Conversation:
        conversation.status = ConversationStatus.handed_off
        conversation.handed_off_at = datetime.now(timezone.utc)
        if reason:
            conversation.qualification_reason = reason
        await commit_with_retry(self.db)
        await self.db.refresh(conversation)
        logger.info(
            "conversation_handed_off",
            conversation_id=conversation.id,
            reason=reason,
        )
        return conversation

    async def mark_human_replied(self, conversation: Conversation) -> Conversation:
        """Mute: un asesor ya escribió en público al cliente."""
        if getattr(conversation, "human_replied_at", None):
            return conversation
        conversation.human_replied_at = datetime.now(timezone.utc)
        await commit_with_retry(self.db)
        await self.db.refresh(conversation)
        logger.info(
            "conversation_human_replied",
            conversation_id=conversation.id,
        )
        return conversation

    async def clear_human_reply(self, conversation: Conversation) -> Conversation:
        """Unmute: Chatwoot volvió a pending (el equipo le regresa el hilo al bot)."""
        if getattr(conversation, "human_replied_at", None) is None:
            return conversation
        conversation.human_replied_at = None
        await commit_with_retry(self.db)
        await self.db.refresh(conversation)
        logger.info(
            "conversation_human_reply_cleared",
            conversation_id=conversation.id,
        )
        return conversation

    async def resume_bot(self, conversation: Conversation) -> Conversation:
        """Vuelve a status active y quita el mute humano."""
        previous = conversation.status.value
        changed = False
        if conversation.status != ConversationStatus.active:
            conversation.status = ConversationStatus.active
            conversation.handed_off_at = None
            changed = True
        if getattr(conversation, "human_replied_at", None) is not None:
            conversation.human_replied_at = None
            changed = True
        if not changed:
            return conversation
        await commit_with_retry(self.db)
        await self.db.refresh(conversation)
        logger.info(
            "conversation_bot_resumed",
            conversation_id=conversation.id,
            previous_status=previous,
        )
        return conversation

    async def delete_conversation(self, conversation: Conversation) -> None:
        """Elimina conversación y mensajes (cascade). Útil para pruebas."""
        conv_id = conversation.id
        await self.db.delete(conversation)
        await commit_with_retry(self.db)
        logger.info("conversation_deleted", conversation_id=conv_id)

    async def _create_lead_in_odoo(self, conversation: Conversation) -> None:
        """Crea o vincula partner y crea crm.lead (solo si Odoo está habilitado)."""
        settings = get_settings()
        if not settings.odoo_enabled:
            return

        async with OdooClient() as odoo:
            partner_id: Optional[int] = None

            if conversation.user_phone:
                partner_id = await odoo.find_partner_by_phone(conversation.user_phone)
            if not partner_id and conversation.user_email:
                partner_id = await odoo.find_partner_by_email(conversation.user_email)

            if not partner_id and (conversation.user_name or conversation.user_phone):
                partner_id = await odoo.create_partner(
                    name=conversation.user_name
                    or f"Prospecto {conversation.channel.value}",
                    phone=conversation.user_phone,
                    email=conversation.user_email,
                )
                conversation.odoo_partner_id = partner_id

            summary_lines = [
                "<b>Conversación capturada por el agente GIA (Chatwoot)</b><br/><br/>"
            ]
            for m in conversation.messages[-20:]:
                role = "Cliente" if m.direction == Direction.inbound else "Agente"
                summary_lines.append(f"<b>{role}:</b> {m.body}<br/>")
            description = "".join(summary_lines)

            if conversation.score >= 12:
                priority = "3"
            elif conversation.score >= 9:
                priority = "2"
            elif conversation.score >= 6:
                priority = "1"
            else:
                priority = "0"

            lead = OdooLeadCreate(
                name=(
                    f"[{conversation.channel.value.upper()}] "
                    f"{conversation.user_name or conversation.external_user_id}"
                ),
                contact_name=conversation.user_name,
                phone=conversation.user_phone,
                mobile=conversation.user_phone,
                email_from=conversation.user_email,
                description=description,
                source=conversation.channel.value.capitalize(),
                priority=priority,
            )
            lead_id = await odoo.create_lead(lead)
            conversation.odoo_lead_id = lead_id

            logger.info(
                "lead_created_in_odoo",
                conversation_id=conversation.id,
                lead_id=lead_id,
                score=conversation.score,
            )

    async def _handoff_to_human(self, conversation: Conversation) -> None:
        """Crea mail.activity en Odoo (solo si Odoo está habilitado)."""
        settings = get_settings()
        if not settings.odoo_enabled:
            return
        if not conversation.odoo_lead_id:
            return
        if conversation.status == ConversationStatus.handed_off:
            return

        async with OdooClient() as odoo:
            signals = conversation.score_breakdown.get("signals", [])
            matched = [s for s in signals if s.get("matched")]
            evidence_lines = [
                f"• {s['name']}: {s.get('evidence', '')}" for s in matched
            ]
            note = (
                f"<b>Lead caliente — score {conversation.score}</b><br/>"
                f"Canal: {conversation.channel.value}<br/><br/>"
                f"<b>Señales detectadas:</b><br/>"
                + "<br/>".join(evidence_lines)
                + "<br/><br/>Revisar conversación y contactar lo antes posible."
            )
            await odoo.create_activity(
                lead_id=conversation.odoo_lead_id,
                summary="Contactar lead caliente (Chatwoot)",
                note=note,
            )
            await odoo.post_internal_note(
                lead_id=conversation.odoo_lead_id,
                body=note,
            )

        conversation.status = ConversationStatus.handed_off
        logger.info(
            "lead_handed_off",
            conversation_id=conversation.id,
            lead_id=conversation.odoo_lead_id,
        )
