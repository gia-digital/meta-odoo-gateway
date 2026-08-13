"""Webhook del Agent Bot de Chatwoot."""
from __future__ import annotations

import hmac
import hashlib
import json
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.conversation import Channel
from app.models.db import SessionLocal
from app.models.schemas import NormalizedMessage
from app.services.chatwoot_client import ChatwootClient, ChatwootError
from app.services.conversation import ConversationService

router = APIRouter(prefix="/webhook", tags=["chatwoot"])
logger = get_logger(__name__)


def _verify_chatwoot_signature(body: bytes, signature: Optional[str], secret: str) -> bool:
    if not signature or not secret:
        return False
    digest = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    # Chatwoot may send raw hex or sha256=<hex>
    received = signature.removeprefix("sha256=")
    return hmac.compare_digest(digest, received)


def _message_type_is_incoming(raw: Any) -> bool:
    """message_type puede ser int (0=incoming) o string."""
    if raw is None:
        return False
    if isinstance(raw, int):
        return raw == 0
    s = str(raw).lower()
    return s in ("incoming", "0")


def _extract_event(payload: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    event = str(payload.get("event") or "")
    return event, payload


def _conversation_id(payload: Dict[str, Any]) -> Optional[int]:
    conv = payload.get("conversation") or {}
    for key in ("id", "display_id"):
        val = conv.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                continue
    # Algunos payloads ponen conversation_id en raíz / message
    for key in ("conversation_id",):
        val = payload.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                continue
    msg = payload.get("message") or {}
    val = msg.get("conversation_id")
    if val is not None:
        try:
            return int(val)
        except (TypeError, ValueError):
            return None
    return None


def _conversation_status(payload: Dict[str, Any]) -> str:
    conv = payload.get("conversation") or {}
    return str(conv.get("status") or "").lower()


def _incoming_content(payload: Dict[str, Any]) -> Optional[str]:
    msg = payload.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if content:
            return str(content)
        mtype = msg.get("message_type")
        if not _message_type_is_incoming(mtype):
            return None
    content = payload.get("content")
    if content:
        return str(content)
    return None


def _is_incoming_event(payload: Dict[str, Any]) -> bool:
    msg = payload.get("message")
    if isinstance(msg, dict) and "message_type" in msg:
        return _message_type_is_incoming(msg.get("message_type"))
    if "message_type" in payload:
        return _message_type_is_incoming(payload.get("message_type"))
    # Sin tipo: asumir incoming si hay content
    return bool(_incoming_content(payload))


def _contact_identity(payload: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """
    Returns (external_user_id, user_name, user_phone, user_email).
    Prefer WhatsApp phone / source_id.
    """
    contact = payload.get("contact") or {}
    sender = payload.get("sender") or {}
    meta = (payload.get("conversation") or {}).get("meta") or {}
    sender_meta = meta.get("sender") or {}

    name = (
        contact.get("name")
        or sender.get("name")
        or sender_meta.get("name")
    )
    email = contact.get("email") or sender.get("email")
    phone = (
        contact.get("phone_number")
        or contact.get("identifier")
        or sender.get("phone_number")
        or sender_meta.get("phone_number")
    )
    source_id = (
        payload.get("source_id")
        or (payload.get("message") or {}).get("source_id")
        or contact.get("identifier")
        or sender_meta.get("identifier")
    )

    external = str(phone or source_id or contact.get("id") or sender.get("id") or "unknown")
    # Normalizar teléfono sin +
    if phone:
        digits = "".join(c for c in str(phone) if c.isdigit())
        if digits:
            external = digits

    return external, (str(name) if name else None), (str(phone) if phone else None), (
        str(email) if email else None
    )


async def _process_incoming_message(payload: Dict[str, Any]) -> None:
    settings = get_settings()
    if not settings.chatwoot_enabled:
        return

    content = _incoming_content(payload)
    if not content or not content.strip():
        logger.info("chatwoot_skip_empty_content")
        return

    if not _is_incoming_event(payload):
        logger.info("chatwoot_skip_non_incoming")
        return

    status_conv = _conversation_status(payload)
    # Solo responder mientras el bot tiene el hilo (pending). Si ya está open, humano.
    if status_conv and status_conv not in ("pending", ""):
        logger.info("chatwoot_skip_not_pending", status=status_conv)
        return

    cw_conv_id = _conversation_id(payload)
    if not cw_conv_id:
        logger.warning("chatwoot_missing_conversation_id")
        return

    external_user_id, user_name, user_phone, user_email = _contact_identity(payload)
    channel = Channel.whatsapp  # inbox WA vía Chatwoot

    async with SessionLocal() as db:
        service = ConversationService(db)
        conv = await service.get_or_create(
            channel=channel,
            external_user_id=external_user_id,
            user_name=user_name,
        )
        nm = NormalizedMessage(
            channel=channel.value,
            external_user_id=external_user_id,
            text=content.strip(),
            external_message_id=str(
                (payload.get("message") or {}).get("id") or payload.get("id") or ""
            )
            or None,
            user_name=user_name,
            user_phone=user_phone,
            raw=payload,
        )
        await service.add_inbound_message(conv, nm)
        await service.process_after_message(conv)

        # Si ya estaba escalada, no responder como bot
        if conv.status.value == "handed_off":
            logger.info("chatwoot_skip_already_handed_off", conversation_id=conv.id)
            return

        from app.services.gia_agent import BotContext, run_gia_agent

        ctx = BotContext(
            db=db,
            conversation=conv,
            channel=channel,
            external_user_id=external_user_id,
            chatwoot_conversation_id=cw_conv_id,
            user_name=user_name or conv.user_name,
            user_phone=user_phone or conv.user_phone,
            user_email=user_email or conv.user_email,
        )

        try:
            reply = await run_gia_agent(
                ctx=ctx,
                user_message=content.strip(),
                history_messages=conv.messages,
            )
        except Exception as exc:
            logger.exception("chatwoot_agent_run_failed", error=str(exc))
            reply = (
                "Disculpe, tengo un problema técnico momentáneo. "
                "En breve un asesor de GIA le atenderá."
            )
            try:
                async with ChatwootClient() as cw:
                    await cw.handoff_to_human(cw_conv_id)
                await service.mark_handed_off(conv, reason=f"agent_error: {exc}")
            except Exception as handoff_exc:
                logger.error("chatwoot_error_handoff_failed", error=str(handoff_exc))

        try:
            async with ChatwootClient() as cw:
                sent = await cw.send_message(cw_conv_id, reply)
            await service.add_outbound_message(
                conv,
                reply,
                external_message_id=str(sent.get("id") or "") or None,
                raw=sent if isinstance(sent, dict) else {},
            )
        except ChatwootError as exc:
            logger.error("chatwoot_reply_failed", error=str(exc))


@router.post("/chatwoot", status_code=200)
async def chatwoot_agent_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_chatwoot_signature: Optional[str] = Header(
        default=None, alias="X-Chatwoot-Signature"
    ),
) -> Dict[str, str]:
    """
    Endpoint `outgoing_url` del Agent Bot de Chatwoot.
    Responde 200 de inmediato y genera la respuesta en background.
    """
    settings = get_settings()
    body = await request.body()

    if not settings.chatwoot_enabled:
        return {"status": "disabled"}

    secret = settings.chatwoot_webhook_secret
    if secret:
        if not _verify_chatwoot_signature(body, x_chatwoot_signature, secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Chatwoot webhook signature",
            )

    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event, payload = _extract_event(payload)
    logger.info("chatwoot_webhook_event", event=event)

    if event in ("message_created", "message_updated", ""):
        # "" por si el payload viene sin event pero con content (tests)
        if event == "message_updated":
            return {"status": "ignored", "reason": "message_updated"}
        background_tasks.add_task(_process_incoming_message, payload)
        return {"status": "ok", "queued": "true"}

    return {"status": "ignored", "event": event or "unknown"}
