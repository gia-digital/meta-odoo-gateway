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


# Stickers (WA/IG/FB) suelen llegar sin texto. Chatwoot mapea sticker de WhatsApp
# a file_type=image; el mime/extension webp (o file_type=sticker) los distingue
# de fotos reales.
_STICKER_FILE_TYPES = frozenset({"sticker"})
_IMAGE_FILE_TYPES = frozenset({"image"})
_AUDIO_FILE_TYPES = frozenset({"audio"})
_VIDEO_FILE_TYPES = frozenset({"video"})
_FILE_FILE_TYPES = frozenset({"file", "document"})
_SKIP_DESCRIBE_TYPES = frozenset(
    {"location", "contact", "fallback", "share", "story_mention", "embed"}
)
_WEBP_MARKERS = (".webp", "image/webp", "webp")


def _attachment_blob(att: Any) -> Dict[str, Any]:
    return att if isinstance(att, dict) else {}


def _attachment_haystack(att: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in (
        "file_type",
        "content_type",
        "extension",
        "file_name",
        "filename",
        "data_url",
        "thumb_url",
        "external_url",
    ):
        val = att.get(key)
        if val:
            parts.append(str(val).lower())
    meta = att.get("meta") or att.get("metadata") or {}
    if isinstance(meta, dict):
        for val in meta.values():
            if val is not None and not isinstance(val, (dict, list)):
                parts.append(str(val).lower())
    return " ".join(parts)


def _looks_like_webp_sticker(att: Dict[str, Any]) -> bool:
    """WhatsApp stickers son webp; Chatwoot los guarda como image."""
    hay = _attachment_haystack(att)
    if not any(marker in hay for marker in _WEBP_MARKERS):
        return False
    # sticker_id (Messenger) o animated refuerzan el caso
    if "sticker" in hay or att.get("sticker_id") is not None:
        return True
    file_type = str(att.get("file_type") or "").lower()
    return file_type in _IMAGE_FILE_TYPES or file_type == ""


def attachment_kind(att: Any) -> str:
    """
    Clasifica un adjunto Chatwoot: sticker | image | audio | video | file |
    location | contact | other.
    """
    blob = _attachment_blob(att)
    file_type = str(blob.get("file_type") or "").lower().strip()

    if file_type in _STICKER_FILE_TYPES or _looks_like_webp_sticker(blob):
        return "sticker"
    if file_type in _IMAGE_FILE_TYPES:
        return "image"
    if file_type in _AUDIO_FILE_TYPES:
        return "audio"
    if file_type in _VIDEO_FILE_TYPES:
        return "video"
    if file_type in _FILE_FILE_TYPES:
        return "file"
    if file_type in ("location",):
        return "location"
    if file_type in ("contact",):
        return "contact"
    if file_type in _SKIP_DESCRIBE_TYPES:
        return "other"
    if file_type:
        return "file"
    # Sin file_type: webp → sticker; si no, archivo genérico
    if _looks_like_webp_sticker(blob):
        return "sticker"
    return "file"


def attachment_kinds(payload: Dict[str, Any]) -> List[str]:
    return [attachment_kind(att) for att in attachments_of(payload)]


def batch_attachment_kinds(payloads: List[Dict[str, Any]]) -> List[str]:
    kinds: List[str] = []
    for payload in payloads:
        kinds.extend(attachment_kinds(payload))
    return kinds


def attachments_are_sticker_only(kinds: List[str]) -> bool:
    return bool(kinds) and all(k == "sticker" for k in kinds)


def primary_attachment_kind(kinds: List[str]) -> str:
    """Prioriza el tipo que debe guiar la respuesta (no sticker si hay media real)."""
    priority = ("file", "audio", "video", "image", "location", "contact", "sticker", "other")
    present = set(kinds)
    for kind in priority:
        if kind in present:
            return kind
    return "file"


def attachment_placeholder(kind: str) -> str:
    return {
        "sticker": "[sticker]",
        "image": "[imagen adjunta]",
        "audio": "[audio adjunto]",
        "video": "[video adjunto]",
        "file": "[archivo adjunto]",
        "location": "[ubicacion]",
        "contact": "[contacto]",
    }.get(kind, "[archivo adjunto]")


def attachment_describe_reply(kind: str) -> Optional[str]:
    """
    Texto fijo pidiendo descripción, o None si no conviene preguntar
    (sticker / location / contact / other).
    """
    if kind in ("sticker", "location", "contact", "other"):
        return None
    noun = {
        "image": "imagen",
        "audio": "audio",
        "video": "video",
        "file": "archivo",
    }.get(kind, "archivo")
    return (
        f"Recibí su {noun}. ¿Puede describirlo por texto para poder ayudarle?"
    )


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
