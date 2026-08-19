"""Parseo de payloads Chatwoot (sin I/O)."""
from typing import Any, Dict, List, Optional


def conversation_status(payload: Dict[str, Any]) -> str:
    conv = payload.get("conversation") or payload
    if not isinstance(conv, dict):
        return ""
    return str(conv.get("status") or "").lower()


def _as_message(payload: Dict[str, Any]) -> Dict[str, Any]:
    msg = payload.get("message")
    if isinstance(msg, dict):
        return msg
    return payload


def _sender_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    for source in (payload.get("sender"), _as_message(payload).get("sender")):
        if isinstance(source, dict) and source:
            return source
    return {}


def is_outgoing_message(payload: Dict[str, Any]) -> bool:
    msg = _as_message(payload)
    raw = msg.get("message_type")
    if raw is None:
        raw = payload.get("message_type")
    if raw is None:
        return False
    if isinstance(raw, int):
        return raw == 1
    return str(raw).lower() in ("outgoing", "1")


def is_incoming_message(payload: Dict[str, Any]) -> bool:
    msg = _as_message(payload)
    raw = msg.get("message_type")
    if raw is None:
        raw = payload.get("message_type")
    if raw is None:
        return False
    if isinstance(raw, int):
        return raw == 0
    return str(raw).lower() in ("incoming", "0")


def is_private_message(payload: Dict[str, Any]) -> bool:
    msg = _as_message(payload)
    if msg.get("private") is True:
        return True
    return payload.get("private") is True


def sender_is_human_agent(payload: Dict[str, Any]) -> bool:
    """True si el sender es un agente humano (no bot ni contacto)."""
    sender = _sender_dict(payload)
    atype = str(sender.get("type") or "").lower()
    if atype in ("agent_bot", "bot", "contact"):
        return False
    return atype in ("user", "agent")


def is_human_public_outgoing(payload: Dict[str, Any]) -> bool:
    """Mensaje público de un asesor al cliente (mute del bot)."""
    if not is_outgoing_message(payload):
        return False
    if is_private_message(payload):
        return False
    return sender_is_human_agent(payload)


def human_assignee_name(payload: Dict[str, Any]) -> Optional[str]:
    """Nombre del agente humano, o None si no hay assignee / es el bot."""
    conv = payload.get("conversation") if isinstance(payload.get("conversation"), dict) else payload
    if not isinstance(conv, dict):
        return None
    meta = conv.get("meta") or {}
    assignee = meta.get("assignee") or conv.get("assignee")
    if not assignee:
        return None
    if isinstance(assignee, dict):
        atype = str(assignee.get("type") or "").lower()
        if atype in ("agent_bot", "bot"):
            return None
        name = (
            assignee.get("name")
            or assignee.get("available_name")
            or assignee.get("id")
        )
        return str(name) if name else "human"
    return str(assignee)


def attachments_of(payload: Dict[str, Any]) -> List[Any]:
    msg = payload.get("message")
    if isinstance(msg, dict) and msg.get("attachments"):
        atts = msg.get("attachments")
        return atts if isinstance(atts, list) else []
    atts = payload.get("attachments")
    return atts if isinstance(atts, list) else []


def has_attachments(payload: Dict[str, Any]) -> bool:
    return bool(attachments_of(payload))


def incoming_message_source_id(payload: Dict[str, Any]) -> Optional[str]:
    """ID del mensaje en el canal (WhatsApp Cloud → wamid… en ``source_id``)."""
    msg = _as_message(payload)
    for source in (msg.get("source_id"), payload.get("source_id")):
        if source:
            return str(source)
    return None


def latest_incoming_source_id(payloads: List[Dict[str, Any]]) -> Optional[str]:
    """Último source_id entrante; marcar uno basta (Meta propaga a anteriores)."""
    for payload in reversed(payloads):
        if not is_incoming_message(payload):
            continue
        source_id = incoming_message_source_id(payload)
        if source_id:
            return source_id
    return None


def latest_incoming_wamid_from_conversation_payload(
    payload: Dict[str, Any],
) -> Optional[str]:
    """Busca wamid entrante embebido en ``conversation.messages`` del webhook."""
    conv = payload.get("conversation")
    if not isinstance(conv, dict):
        return None
    messages = conv.get("messages")
    if isinstance(messages, list):
        return latest_incoming_source_id(messages)
    return None


def latest_inbound_wamid_from_db_messages(messages: List[Any]) -> Optional[str]:
    """Último wamid entrante persistido en Postgres (``raw_payload`` del webhook)."""
    for msg in reversed(messages):
        direction = getattr(msg, "direction", None)
        if direction is None and isinstance(msg, dict):
            direction = msg.get("direction")
        dir_val = getattr(direction, "value", direction)
        if str(dir_val or "").lower() != "inbound":
            continue
        raw = getattr(msg, "raw_payload", None)
        if raw is None and isinstance(msg, dict):
            raw = msg.get("raw_payload")
        if isinstance(raw, dict):
            source_id = incoming_message_source_id(raw)
            if source_id:
                return source_id
    return None


def latest_incoming_source_id_from_messages(
    messages: List[Dict[str, Any]],
) -> Optional[str]:
    """Último wamid entrante en el historial de Chatwoot (p. ej. reply humano)."""
    return latest_incoming_source_id(messages)


def resolve_inbound_wamid_for_human_reply(
    cw_conv_id: int,
    payload: Dict[str, Any],
    db_messages: Optional[List[Any]] = None,
) -> Optional[str]:
    """Orden: cache en memoria → DB → webhook → (caller usa API si sigue vacío)."""
    from app.services.turn_guard import last_inbound_wamid

    cached = last_inbound_wamid(cw_conv_id)
    if cached:
        return cached
    if db_messages:
        stored = latest_inbound_wamid_from_db_messages(db_messages)
        if stored:
            return stored
    return latest_incoming_wamid_from_conversation_payload(payload)
