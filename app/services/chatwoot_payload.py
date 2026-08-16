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
