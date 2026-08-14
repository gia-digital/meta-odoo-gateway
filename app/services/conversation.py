"""
Servicio de orquestación de conversaciones.

Une:
- Persistencia (Conversation, Message)
- Scoring local (señal secundaria)
- Calificación por el agente GIA (Chatwoot)
- Creación de leads en Odoo (solo si ODOO_ENABLED=true)
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.logging import get_logger
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


class ConversationService:
    """Orquesta el ciclo de vida de una conversación."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_or_create(
        self, channel: Channel, external_user_id: str, user_name: Optional[str] = None
    ) -> Conversation:
        stmt = (
            select(Conversation)
            .where(
                Conversation.channel == channel,
                Conversation.external_user_id == external_user_id,
                Conversation.status.in_(
                    [
                        ConversationStatus.active,
                        ConversationStatus.qualified,
                        ConversationStatus.handed_off,
                    ]
                ),
            )
            .options(selectinload(Conversation.messages))
            .order_by(Conversation.created_at.desc())
        )
        result = await self.db.execute(stmt)
        conv = result.scalars().first()
        if conv:
            return conv

        conv = Conversation(
            channel=channel,
            external_user_id=external_user_id,
            user_name=user_name,
            status=ConversationStatus.active,
            qualification_source=QualificationSource.none,
        )
        self.db.add(conv)
        await self.db.commit()
        await self.db.refresh(conv, ["messages"])
        logger.info("conversation_created", id=conv.id, channel=channel.value)
        return conv

    async def add_inbound_message(
        self, conversation: Conversation, message: NormalizedMessage
    ) -> Message:
        msg = Message(
            conversation_id=conversation.id,
            direction=Direction.inbound,
            body=message.text,
            external_message_id=message.external_message_id,
            raw_payload=message.raw,
        )
        self.db.add(msg)

        if message.user_name and not conversation.user_name:
            conversation.user_name = message.user_name
        if message.user_phone and not conversation.user_phone:
            conversation.user_phone = message.user_phone

        await self.db.commit()
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

        await self.db.commit()

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
        elif conversation.status == ConversationStatus.active:
            conversation.status = ConversationStatus.qualified

        # Recalcular score para contexto en dashboard
        if conversation.messages:
            score_result = score_conversation(conversation.messages)
            conversation.score = score_result.total
            conversation.score_breakdown = {
                "signals": [s.model_dump() for s in score_result.signals]
            }

        await self.db.commit()
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
        msg = Message(
            conversation_id=conversation.id,
            direction=Direction.outbound,
            body=body,
            external_message_id=external_message_id,
            raw_payload=raw or {},
        )
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(conversation, ["messages"])
        return msg

    async def mark_handed_off(
        self, conversation: Conversation, *, reason: Optional[str] = None
    ) -> Conversation:
        conversation.status = ConversationStatus.handed_off
        if reason:
            conversation.qualification_reason = reason
        await self.db.commit()
        await self.db.refresh(conversation)
        logger.info(
            "conversation_handed_off",
            conversation_id=conversation.id,
            reason=reason,
        )
        return conversation

    async def resume_bot(self, conversation: Conversation) -> Conversation:
        """Vuelve a status active para que el Agent Bot pueda atender de nuevo."""
        if conversation.status == ConversationStatus.active:
            return conversation
        previous = conversation.status.value
        conversation.status = ConversationStatus.active
        await self.db.commit()
        await self.db.refresh(conversation)
        logger.info(
            "conversation_bot_resumed",
            conversation_id=conversation.id,
            previous_status=previous,
        )
        return conversation

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
