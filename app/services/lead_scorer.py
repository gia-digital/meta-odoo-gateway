"""
Motor de scoring de leads.

Recibe el historial completo de la conversación y aplica reglas para
calcular un score que determina:
- Si crear un lead en Odoo
- Si notificar a un agente humano

Las reglas están diseñadas para ser fácilmente configurables vía YAML/JSON
en una iteración futura. Aquí van en código por simplicidad.
"""
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.conversation import Message
from app.models.schemas import ScoreResult, ScoreSignal

logger = get_logger(__name__)


# ============================================================
# Catálogo de palabras clave (ajustar al negocio del cliente)
# ============================================================

PRODUCT_KEYWORDS = [
    "acero", "lámina", "lamina", "rollo", "hoja", "cinta",
    "tubería", "tuberia", "tubo", "acanalado", "galvanizad",
    "pintro", "varilla", "alambre", "deck", "solera",
    "calibre", "cotización", "cotizacion", "material",
]

BUDGET_KEYWORDS = [
    "presupuesto", "precio", "cuánto cuesta", "cuanto cuesta",
    "costo", "tarifa", "cotización", "cotizacion", "cuanto vale",
    "tonelada", "toneladas", "ton", "tonelaje", "volumen",
    "camión", "camion", "cantidad",
]

# Detecta montos: $1000, 5,000 MXN, USD 200, 1k, etc.
BUDGET_AMOUNT_PATTERN = re.compile(
    r"(?:\$|usd|mxn|eur|mx\$|us\$)\s*[\d,]+(?:\.\d+)?|"
    r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|"
    r"\b\d+\s*(?:k|mil|millones?)\b",
    flags=re.IGNORECASE,
)

URGENCY_KEYWORDS = [
    "urgente", "hoy", "mañana", "esta semana", "lo antes posible",
    "asap", "rápido", "rapido", "ya", "necesito ahora",
    "este mes", "para el", "antes de",
]

DECISION_KEYWORDS = [
    "quiero cotizar", "necesito cotización", "necesito cotizacion",
    "quiero comprar", "quiero adquirir", "vamos a comprar",
    "listo para", "me interesa", "envíen cotización", "envien cotizacion",
    "siguiente paso", "agendar", "agéndame", "agendame",
    "hablar con ventas", "hablar con un asesor",
]

HUMAN_REQUEST_KEYWORDS = [
    "hablar con alguien", "hablar con una persona", "asesor",
    "vendedor", "ejecutivo", "agente humano", "persona real",
    "llamar", "llámenme", "llamenme", "marcar", "ventas",
]

CONTACT_DATA_PATTERNS = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "phone": re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,4}[\s-]?\d{3,4}\b"),
}


# ============================================================
# Reglas (cada una otorga puntos si se cumple)
# ============================================================


@dataclass
class Rule:
    name: str
    points: int
    description: str


RULES = [
    Rule("product_mentioned", 2, "Mencionó un producto o servicio específico"),
    Rule("budget_mentioned", 3, "Indicó presupuesto o preguntó por precio con monto"),
    Rule("urgency_signaled", 2, "Señaló urgencia o plazo definido"),
    Rule("decision_intent", 4, "Expresó intención clara de contratar/comprar"),
    Rule("multiple_messages", 1, "Conversación con 3+ mensajes del usuario"),
    Rule("shared_contact", 2, "Compartió email o teléfono"),
    Rule("requested_human", 5, "Pidió hablar con una persona real"),
]


# ============================================================
# Lógica de detección por regla
# ============================================================


def _full_user_text(messages: Sequence[Message]) -> str:
    """Concatena solo los mensajes entrantes (del usuario) en lowercase."""
    parts = [m.body.lower() for m in messages if m.direction.value == "inbound"]
    return " | ".join(parts)


def _user_message_count(messages: Sequence[Message]) -> int:
    return sum(1 for m in messages if m.direction.value == "inbound")


def _contains_any(text: str, keywords: List[str]) -> Optional[str]:
    for kw in keywords:
        if kw in text:
            return kw
    return None


def _evaluate_rule(rule: Rule, text: str, messages: Sequence[Message]) -> ScoreSignal:
    matched = False
    evidence: Optional[str] = None

    if rule.name == "product_mentioned":
        match = _contains_any(text, PRODUCT_KEYWORDS)
        if match:
            matched, evidence = True, f"keyword: {match}"

    elif rule.name == "budget_mentioned":
        kw_match = _contains_any(text, BUDGET_KEYWORDS)
        amt_match = BUDGET_AMOUNT_PATTERN.search(text)
        if kw_match and amt_match:
            matched, evidence = True, f"keyword: {kw_match}, amount: {amt_match.group(0)}"
        elif amt_match:
            # Mencionó monto explícito incluso sin keyword
            matched, evidence = True, f"amount: {amt_match.group(0)}"

    elif rule.name == "urgency_signaled":
        match = _contains_any(text, URGENCY_KEYWORDS)
        if match:
            matched, evidence = True, f"keyword: {match}"

    elif rule.name == "decision_intent":
        match = _contains_any(text, DECISION_KEYWORDS)
        if match:
            matched, evidence = True, f"keyword: {match}"

    elif rule.name == "multiple_messages":
        count = _user_message_count(messages)
        if count >= 3:
            matched, evidence = True, f"user messages: {count}"

    elif rule.name == "shared_contact":
        email = CONTACT_DATA_PATTERNS["email"].search(text)
        phone = CONTACT_DATA_PATTERNS["phone"].search(text)
        if email or phone:
            found = []
            if email:
                found.append(f"email: {email.group(0)}")
            if phone:
                found.append(f"phone: {phone.group(0)}")
            matched, evidence = True, "; ".join(found)

    elif rule.name == "requested_human":
        match = _contains_any(text, HUMAN_REQUEST_KEYWORDS)
        if match:
            matched, evidence = True, f"keyword: {match}"

    return ScoreSignal(
        name=rule.name,
        points=rule.points if matched else 0,
        matched=matched,
        evidence=evidence,
    )


# ============================================================
# API pública
# ============================================================


def score_conversation(messages: Sequence[Message]) -> ScoreResult:
    """
    Calcula el score de una conversación y decide qué acciones tomar.
    """
    settings = get_settings()
    text = _full_user_text(messages)

    signals = [_evaluate_rule(rule, text, messages) for rule in RULES]
    total = sum(s.points for s in signals)

    create_lead = total >= settings.lead_creation_threshold
    notify_human = total >= settings.human_handoff_threshold

    result = ScoreResult(
        total=total,
        signals=signals,
        create_lead=create_lead,
        notify_human=notify_human,
    )

    logger.info(
        "score_calculated",
        total=total,
        create_lead=create_lead,
        notify_human=notify_human,
        matched=[s.name for s in signals if s.matched],
    )
    return result
