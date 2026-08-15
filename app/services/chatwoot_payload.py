"""Parseo de payloads Chatwoot (sin I/O)."""
from typing import Any, Dict, List, Optional


def conversation_status(payload: Dict[str, Any]) -> str:
    conv = payload.get("conversation") or payload
    if not isinstance(conv, dict):
        return ""
    return str(conv.get("status") or "").lower()


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
