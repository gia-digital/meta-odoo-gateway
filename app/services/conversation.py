"""
Servicio de orquestación de conversaciones.

Es el "cerebro" que une:
- Persistencia (Conversation, Message en la DB del gateway)
- Scoring (lead_scorer)
- Creación de leads en Odoo (odoo_client)
- Handoff a humano (post-process)
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.models.conversation import (
    Channel,
    Conversation,
    ConversationStatus,
    Direction,
    Message,
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
                    [ConversationStatus.active, ConversationStatus.qualified]
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

        # Actualizar datos del contacto si vinieron en el mensaje
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
        1. Recalcular score
        2. Si supera umbral → crear lead en Odoo (si no existe)
        3. Si supera umbral de handoff → notificar humano
        """
        score_result = score_conversation(conversation.messages)
        conversation.score = score_result.total
        conversation.score_breakdown = {
            "signals": [s.model_dump() for s in score_result.signals]
        }

        # 1. Crear lead si toca y no existe
        if score_result.create_lead and conversation.odoo_lead_id is None:
            await self._create_lead_in_odoo(conversation)
            conversation.status = ConversationStatus.qualified

        # 2. Notificar humano si toca
        if score_result.notify_human and conversation.odoo_lead_id:
            await self._handoff_to_human(conversation)

        await self.db.commit()

    async def _create_lead_in_odoo(self, conversation: Conversation) -> None:
        """Crea o vincula partner y crea crm.lead."""
        async with OdooClient() as odoo:
            partner_id: Optional[int] = None

            # Intentar reusar partner existente
            if conversation.user_phone:
                partner_id = await odoo.find_partner_by_phone(conversation.user_phone)
            if not partner_id and conversation.user_email:
                partner_id = await odoo.find_partner_by_email(conversation.user_email)

            # Crear partner si no existe y tenemos algún dato
            if not partner_id and (conversation.user_name or conversation.user_phone):
                partner_id = await odoo.create_partner(
                    name=conversation.user_name or f"Prospecto {conversation.channel.value}",
                    phone=conversation.user_phone,
                    email=conversation.user_email,
                )
                conversation.odoo_partner_id = partner_id

            # Construir resumen de la conversación
            summary_lines = ["<b>Conversación capturada por Meta Business Agent</b><br/><br/>"]
            for m in conversation.messages[-20:]:  # últimos 20 mensajes
                role = "Cliente" if m.direction == Direction.inbound else "Agente"
                summary_lines.append(f"<b>{role}:</b> {m.body}<br/>")
            description = "".join(summary_lines)

            # Priority según score
            if conversation.score >= 12:
                priority = "3"  # very high
            elif conversation.score >= 9:
                priority = "2"  # high
            elif conversation.score >= 6:
                priority = "1"  # medium
            else:
                priority = "0"

            lead = OdooLeadCreate(
                name=f"[{conversation.channel.value.upper()}] {conversation.user_name or conversation.external_user_id}",
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
        """Crea una mail.activity para que el vendedor tome acción inmediata."""
        if not conversation.odoo_lead_id:
            return
        if conversation.status == ConversationStatus.handed_off:
            return  # ya se hizo

        async with OdooClient() as odoo:
            # Resumen breve de señales
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
                summary="Contactar lead caliente (Meta)",
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
