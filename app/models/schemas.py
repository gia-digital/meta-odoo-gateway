"""Schemas Pydantic para entrada/salida."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ============================================================
# Payloads de Meta (WhatsApp + Messenger)
# ============================================================


class MetaWebhookEntry(BaseModel):
    """Una entrada dentro del webhook de Meta."""

    id: str
    time: Optional[int] = None
    changes: Optional[List[Dict[str, Any]]] = None  # WhatsApp
    messaging: Optional[List[Dict[str, Any]]] = None  # Messenger


class MetaWebhookPayload(BaseModel):
    """Payload top-level del webhook de Meta."""

    object: str  # "whatsapp_business_account" o "page"
    entry: List[MetaWebhookEntry]


class MetaLeadPayload(BaseModel):
    """
    Payload legacy para POST /webhook/meta/lead.
    Preferir LeadCreate / POST /leads como tool del agente.
    """

    channel: str = "whatsapp"  # whatsapp | messenger | instagram
    external_user_id: str
    user_name: Optional[str] = None
    user_phone: Optional[str] = None
    user_email: Optional[str] = None
    reason: Optional[str] = None
    summary: Optional[str] = None
    product_interest: Optional[str] = None
    budget: Optional[str] = None
    timeline: Optional[str] = None
    preferred_contact_time: Optional[str] = None
    handed_off: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LeadCreate(BaseModel):
    """
    Tool del agente GIA: registrar un prospecto calificado para el equipo de ventas.
    """

    channel: str = Field(
        default="whatsapp",
        description="Canal de origen: whatsapp | messenger | instagram",
    )
    external_user_id: str = Field(
        ...,
        description="ID del usuario en el canal (wa_id o PSID)",
    )
    user_name: Optional[str] = Field(
        default=None, description="Nombre completo del contacto o razón social"
    )
    user_phone: Optional[str] = Field(
        default=None, description="Teléfono de contacto"
    )
    user_email: Optional[str] = Field(
        default=None, description="Email de contacto"
    )
    reason: Optional[str] = Field(
        default=None,
        description="Motivo corto (ej. pidió cotización de lámina galvanizada)",
    )
    summary: Optional[str] = Field(
        default=None,
        description="Resumen para el asesor de ventas: empresa, uso, ubicación, notas",
    )
    product_interest: Optional[str] = Field(
        default=None,
        description="Material o línea de interés (aceros planos, tubería, acanalados, etc.)",
    )
    budget: Optional[str] = Field(
        default=None,
        description="Volumen estimado (toneladas) o presupuesto aproximado",
    )
    timeline: Optional[str] = Field(
        default=None,
        description="Urgencia o fecha deseada de entrega",
    )
    preferred_contact_time: Optional[str] = Field(
        default=None, description="Mejor horario para que ventas contacte"
    )
    handed_off: bool = Field(
        default=False,
        description="true si además se escaló la conversación a un asesor humano",
    )


class LeadOut(BaseModel):
    """Lead calificado expuesto por la API y el dashboard."""

    id: int
    channel: str
    external_user_id: str
    user_name: Optional[str] = None
    user_phone: Optional[str] = None
    user_email: Optional[str] = None
    status: str
    qualification_source: str = "none"
    qualification_reason: Optional[str] = None
    product_interest: Optional[str] = None
    lead_summary: Optional[str] = None
    budget: Optional[str] = None
    timeline: Optional[str] = None
    preferred_contact_time: Optional[str] = None
    score: int = 0
    qualified_at: Optional[datetime] = None
    odoo_lead_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# Mensaje normalizado interno
# ============================================================


class NormalizedMessage(BaseModel):
    """
    Representación común de un mensaje, independiente del canal.
    El gateway normaliza WhatsApp/Messenger a esta forma.
    """

    channel: str  # "whatsapp" | "messenger"
    external_user_id: str
    external_message_id: Optional[str] = None
    user_name: Optional[str] = None
    user_phone: Optional[str] = None
    text: str
    raw: Dict[str, Any] = Field(default_factory=dict)


class NormalizedHandover(BaseModel):
    """Evento de handoff / thread control desde Meta."""

    channel: str
    external_user_id: str
    reason: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# Schemas de scoring
# ============================================================


class ScoreSignal(BaseModel):
    """Un componente individual del score."""

    name: str
    points: int
    matched: bool
    evidence: Optional[str] = None


class ScoreResult(BaseModel):
    total: int
    signals: List[ScoreSignal]
    create_lead: bool
    notify_human: bool


# ============================================================
# Schemas para Odoo
# ============================================================


class OdooLeadCreate(BaseModel):
    """Datos para crear un lead en Odoo."""

    name: str
    partner_name: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    email_from: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    team_id: Optional[int] = None
    user_id: Optional[int] = None
    tag_ids: List[int] = Field(default_factory=list)
    priority: str = "1"


# ============================================================
# Schemas para Admin
# ============================================================


class ConversationOut(BaseModel):
    id: int
    channel: str
    external_user_id: str
    user_name: Optional[str]
    user_phone: Optional[str] = None
    user_email: Optional[str] = None
    status: str
    score: int
    score_breakdown: Dict[str, Any]
    qualification_source: str = "none"
    qualification_reason: Optional[str] = None
    product_interest: Optional[str] = None
    lead_summary: Optional[str] = None
    budget: Optional[str] = None
    timeline: Optional[str] = None
    preferred_contact_time: Optional[str] = None
    qualified_at: Optional[datetime] = None
    odoo_lead_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: int
    direction: str
    body: str
    created_at: datetime

    class Config:
        from_attributes = True
