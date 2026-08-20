"""Modelos ORM para conversaciones y mensajes."""
import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db import Base


class Channel(str, enum.Enum):
    whatsapp = "whatsapp"
    messenger = "messenger"
    instagram = "instagram"


class ConversationStatus(str, enum.Enum):
    active = "active"  # IA activa
    qualified = "qualified"  # Lead local listo para revisar
    handed_off = "handed_off"  # Escalado a humano
    closed = "closed"  # Cerrado


class QualificationSource(str, enum.Enum):
    none = "none"
    meta_agent = "meta_agent"
    local_score = "local_score"
    chatwoot_agent = "chatwoot_agent"


class Direction(str, enum.Enum):
    inbound = "inbound"  # Usuario → Agente
    outbound = "outbound"  # Agente → Usuario


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel: Mapped[Channel] = mapped_column(Enum(Channel), index=True, nullable=False)
    # Instagram/Chatwoot source_id puede superar 128 (mid base64 ~160+)
    external_user_id: Mapped[str] = mapped_column(String(512), index=True, nullable=False)
    user_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus), default=ConversationStatus.active, index=True
    )
    score: Mapped[int] = mapped_column(Integer, default=0)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)

    qualification_source: Mapped[QualificationSource] = mapped_column(
        Enum(QualificationSource),
        default=QualificationSource.none,
        index=True,
        nullable=False,
    )
    qualification_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    qualified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    handed_off_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    human_replied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Datos estructurados del lead (tool create_lead / POST /leads)
    product_interest: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    lead_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    budget: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    timeline: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    preferred_contact_time: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    odoo_lead_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    odoo_partner_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[List["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    direction: Mapped[Direction] = mapped_column(Enum(Direction), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    external_message_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )
