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
    name: str  # Título del lead
    partner_name: Optional[str] = None  # Si no hay contact previo
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    email_from: Optional[str] = None
    description: Optional[str] = None  # Resumen / notas
    source: Optional[str] = None  # WhatsApp / Messenger
    team_id: Optional[int] = None
    user_id: Optional[int] = None  # Salesperson
    tag_ids: List[int] = Field(default_factory=list)
    priority: str = "1"  # 0=normal, 1=medium, 2=high, 3=very high


# ============================================================
# Schemas para Admin
# ============================================================


class ConversationOut(BaseModel):
    id: int
    channel: str
    external_user_id: str
    user_name: Optional[str]
    status: str
    score: int
    score_breakdown: Dict[str, Any]
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
