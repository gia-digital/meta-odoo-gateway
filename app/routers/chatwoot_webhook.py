"""Webhook del Agent Bot de Chatwoot."""
from __future__ import annotations

import asyncio
import hmac
import hashlib
import json
import random
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from app.core.agent_behavior import get_agent_behavior
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.conversation import Channel
from app.models.db import SessionLocal
from app.models.schemas import NormalizedMessage
from app.services.chatwoot_client import ChatwootClient, ChatwootError
from app.services.chatwoot_payload import (
    has_attachments,
    is_human_public_outgoing,
)
from app.services.conversation import ConversationService
from app.services.reply_bubbles import (
    first_send_wait_seconds,
    next_bubble_wait_seconds,
    split_reply_bubbles,
)
from app.services.turn_guard import (
    clear_human_reply_guard,
    debounce_payloads,
    has_newer_inbound,
    human_has_replied,
    record_agent_failure,
    record_agent_success,
    record_human_reply,
)

ATTACHMENT_REPLY = (
    "Recibí su archivo. ¿Puede describirlo por texto para poder ayudarle?"
)
AGENT_RETRY_REPLY = (
    "Disculpe, tengo un problema técnico momentáneo. "
    "¿Puede repetir su mensaje en un momento?"
)
AGENT_HANDOFF_REPLY = (
    "Disculpe, tengo un problema técnico. "
    "Un asesor de GIA puede tomar este chat; "
    "si prefiere, ¿puede repetir su mensaje?"
)

router = APIRouter(prefix="/webhook", tags=["chatwoot"])
logger = get_logger(__name__)


def _verify_chatwoot_signature(
    body: bytes,
    signature: Optional[str],
    secret: str,
    timestamp: Optional[str] = None,
) -> bool:
    """
    Chatwoot firma con HMAC-SHA256 sobre ``{timestamp}.{raw_body}``
    (cabeceras X-Chatwoot-Signature + X-Chatwoot-Timestamp).
    También aceptamos firma solo del body (versiones / setups legacy).
    """
    if not signature or not secret:
        return False
    received = signature.removeprefix("sha256=")
    secret_b = secret.encode("utf-8")
    candidates: list[str] = []
    if timestamp:
        signed = f"{timestamp}.".encode("utf-8") + body
        candidates.append(hmac.new(secret_b, signed, hashlib.sha256).hexdigest())
    candidates.append(hmac.new(secret_b, body, hashlib.sha256).hexdigest())
    return any(hmac.compare_digest(digest, received) for digest in candidates)


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


def _merge_incoming_texts(batch: list) -> str:
    texts: list[str] = []
    for item in batch:
        content = _incoming_content(item)
        if content and content.strip() and (not texts or texts[-1] != content.strip()):
            texts.append(content.strip())
    return "\n".join(texts)


def _is_inactive_status(status_conv: str) -> bool:
    return status_conv in ("resolved", "snoozed")


async def _history_has_human_reply(cw_conv_id: int) -> bool:
    """Red de seguridad: el Agent Bot a veces no recibe outgoing humanos."""
    try:
        async with ChatwootClient() as cw:
            messages = await cw.list_messages(cw_conv_id)
    except Exception as exc:
        logger.error(
            "chatwoot_list_messages_failed",
            conversation_id=cw_conv_id,
            error=str(exc),
        )
        return False
    return any(is_human_public_outgoing(item) for item in messages)


async def _process_human_outgoing(payload: Dict[str, Any]) -> None:
    """Mute persistente cuando un asesor escribe en público al cliente."""
    settings = get_settings()
    if not settings.chatwoot_enabled:
        return
    cw_conv_id = _conversation_id(payload)
    if not cw_conv_id:
        logger.warning("chatwoot_human_outgoing_missing_conversation_id")
        return
    record_human_reply(cw_conv_id)
    external_user_id, user_name, _, _ = _contact_identity(payload)
    async with SessionLocal() as db:
        service = ConversationService(db)
        conv = await service.get_or_create(
            channel=Channel.whatsapp,
            external_user_id=external_user_id,
            user_name=user_name,
        )
        await service.mark_human_replied(conv)
    logger.info(
        "chatwoot_human_replied",
        conversation_id=cw_conv_id,
    )


async def _process_incoming_message(payload: Dict[str, Any]) -> None:
    settings = get_settings()
    if not settings.chatwoot_enabled:
        return

    cw_conv_id = _conversation_id(payload)
    if not cw_conv_id:
        logger.warning("chatwoot_missing_conversation_id")
        return

    batch = await debounce_payloads(cw_conv_id, payload)
    if batch is None:
        logger.info("chatwoot_debounced", conversation_id=cw_conv_id)
        return

    incoming_batch = [item for item in batch if _is_incoming_event(item)]
    if not incoming_batch:
        logger.info("chatwoot_skip_non_incoming", conversation_id=cw_conv_id)
        return

    payload = incoming_batch[-1]
    content = _merge_incoming_texts(incoming_batch)
    attached = any(has_attachments(item) for item in incoming_batch)
    started_at = time.monotonic()

    status_conv = _conversation_status(payload)
    if _is_inactive_status(status_conv):
        logger.info(
            "chatwoot_skip_inactive",
            conversation_id=cw_conv_id,
            status=status_conv,
        )
        return

    if not content:
        if attached:
            if human_has_replied(cw_conv_id) and status_conv != "pending":
                logger.info(
                    "chatwoot_skip_human_replied",
                    conversation_id=cw_conv_id,
                    reason="attachment",
                )
                return
            content = ATTACHMENT_REPLY
            await _reply_without_agent(
                payload, cw_conv_id, content, started_at=started_at
            )
            return
        logger.info("chatwoot_skip_empty_content", conversation_id=cw_conv_id)
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

        if status_conv == "pending":
            clear_human_reply_guard(cw_conv_id)
            if getattr(conv, "human_replied_at", None):
                await service.clear_human_reply(conv)
        elif getattr(conv, "human_replied_at", None) or human_has_replied(cw_conv_id):
            record_human_reply(cw_conv_id)
            logger.info(
                "chatwoot_skip_human_replied",
                conversation_id=conv.id,
                chatwoot_conversation_id=cw_conv_id,
            )
            return
        elif status_conv == "open" and await _history_has_human_reply(cw_conv_id):
            record_human_reply(cw_conv_id)
            await service.mark_human_replied(conv)
            logger.info(
                "chatwoot_skip_human_replied",
                conversation_id=conv.id,
                chatwoot_conversation_id=cw_conv_id,
                source="history",
            )
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
            record_agent_success(cw_conv_id)
        except Exception as exc:
            fails = record_agent_failure(cw_conv_id)
            logger.exception(
                "chatwoot_agent_run_failed",
                error=str(exc),
                conversation_id=cw_conv_id,
                fail_count=fails,
            )
            threshold = settings.agent_error_handoff_threshold
            if threshold > 0 and fails >= threshold:
                reply = AGENT_HANDOFF_REPLY
                try:
                    async with ChatwootClient() as cw:
                        await cw.handoff_to_human(
                            cw_conv_id,
                            note=(
                                f"Handoff por {fails} errores seguidos del agente: {exc}"
                            ),
                        )
                    await service.mark_handed_off(conv, reason=f"agent_error: {exc}")
                except Exception as handoff_exc:
                    logger.error(
                        "chatwoot_error_handoff_failed",
                        error=str(handoff_exc),
                        conversation_id=cw_conv_id,
                    )
            else:
                reply = AGENT_RETRY_REPLY

        try:
            await _deliver_reply(
                service, conv, cw_conv_id, reply, started_at=started_at
            )
        except ChatwootError as exc:
            logger.error(
                "chatwoot_reply_failed",
                error=str(exc),
                conversation_id=cw_conv_id,
            )


async def _deliver_reply(
    service,
    conv,
    cw_conv_id: int,
    reply: str,
    *,
    started_at: Optional[float] = None,
) -> None:
    """Envía 1..N burbujas con pausa de escritura; aborta si llegó otro inbound."""
    behavior = await get_agent_behavior()
    bubbles = split_reply_bubbles(
        reply, max_bubbles=behavior.reply_max_bubbles
    )
    if not bubbles:
        return
    elapsed = (time.monotonic() - started_at) if started_at else 0.0
    span = max(
        0.0,
        float(behavior.reply_max_delay_seconds) - float(behavior.reply_min_seconds),
    )
    jitter = random.uniform(0.0, min(4.0, span)) if span else 0.0
    first_wait = first_send_wait_seconds(
        bubbles[0],
        elapsed=elapsed,
        think=behavior.reply_think_seconds,
        chars_per_sec=behavior.reply_chars_per_sec,
        min_total=behavior.reply_min_seconds,
        max_wait=behavior.reply_max_delay_seconds,
        jitter=jitter,
    )
    if first_wait:
        await asyncio.sleep(first_wait)
    if human_has_replied(cw_conv_id):
        logger.info("chatwoot_reply_aborted_human", conversation_id=cw_conv_id)
        return
    if has_newer_inbound(cw_conv_id):
        logger.info("chatwoot_reply_superseded", conversation_id=cw_conv_id)
        return

    min_gap = max(0, int(behavior.reply_bubble_delay_ms)) / 1000.0
    async with ChatwootClient() as cw:
        for i, bubble in enumerate(bubbles):
            if human_has_replied(cw_conv_id):
                logger.info(
                    "chatwoot_reply_aborted_human",
                    conversation_id=cw_conv_id,
                    sent=i,
                )
                return
            if has_newer_inbound(cw_conv_id):
                logger.info(
                    "chatwoot_reply_superseded",
                    conversation_id=cw_conv_id,
                    sent=i,
                )
                return
            if i:
                gap = next_bubble_wait_seconds(
                    bubble,
                    chars_per_sec=behavior.reply_chars_per_sec,
                    min_wait=min_gap,
                    max_wait=min(5.0, behavior.reply_max_delay_seconds),
                )
                if gap:
                    await asyncio.sleep(gap)
                if human_has_replied(cw_conv_id):
                    logger.info(
                        "chatwoot_reply_aborted_human",
                        conversation_id=cw_conv_id,
                        sent=i,
                    )
                    return
                if has_newer_inbound(cw_conv_id):
                    logger.info(
                        "chatwoot_reply_superseded",
                        conversation_id=cw_conv_id,
                        sent=i,
                    )
                    return
            sent = await cw.send_message(cw_conv_id, bubble)
            await service.add_outbound_message(
                conv,
                bubble,
                external_message_id=str(sent.get("id") or "") or None,
                raw=sent if isinstance(sent, dict) else {},
            )
    logger.info(
        "chatwoot_reply_delivered",
        conversation_id=cw_conv_id,
        bubbles=len(bubbles),
        first_wait_s=round(first_wait, 2),
        llm_s=round(elapsed, 2),
    )


async def _reply_without_agent(
    payload: Dict[str, Any],
    cw_conv_id: int,
    reply: str,
    *,
    started_at: Optional[float] = None,
) -> None:
    """Respuesta fija (p. ej. adjunto sin texto) sin llamar al LLM."""
    external_user_id, user_name, user_phone, _ = _contact_identity(payload)
    async with SessionLocal() as db:
        service = ConversationService(db)
        conv = await service.get_or_create(
            channel=Channel.whatsapp,
            external_user_id=external_user_id,
            user_name=user_name,
        )
        await service.add_inbound_message(
            conv,
            NormalizedMessage(
                channel=Channel.whatsapp.value,
                external_user_id=external_user_id,
                text="[archivo adjunto]",
                external_message_id=str(
                    (payload.get("message") or {}).get("id") or payload.get("id") or ""
                )
                or None,
                user_name=user_name,
                user_phone=user_phone,
                raw=payload,
            ),
        )
        try:
            await _deliver_reply(
                service, conv, cw_conv_id, reply, started_at=started_at
            )
        except ChatwootError as exc:
            logger.error(
                "chatwoot_reply_failed",
                error=str(exc),
                conversation_id=cw_conv_id,
            )


@router.post("/chatwoot", status_code=200)
async def chatwoot_agent_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_chatwoot_signature: Optional[str] = Header(
        default=None, alias="X-Chatwoot-Signature"
    ),
    x_chatwoot_timestamp: Optional[str] = Header(
        default=None, alias="X-Chatwoot-Timestamp"
    ),
) -> Dict[str, str]:
    """
    Endpoint `outgoing_url` del Agent Bot de Chatwoot.
    Responde 200 de inmediato y genera la respuesta en background.
    """
    settings = get_settings()
    body = await request.body()

    if not settings.chatwoot_enabled:
        logger.warning("chatwoot_disabled_skip")
        return {"status": "disabled"}

    secret = settings.chatwoot_webhook_secret
    if secret:
        if not _verify_chatwoot_signature(
            body, x_chatwoot_signature, secret, x_chatwoot_timestamp
        ):
            logger.warning(
                "chatwoot_invalid_signature",
                has_signature=bool(x_chatwoot_signature),
                has_timestamp=bool(x_chatwoot_timestamp),
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Chatwoot webhook signature",
            )

    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event, payload = _extract_event(payload)
    logger.info("chatwoot_webhook_event", chatwoot_event=event)

    if event in ("message_created", "message_updated", ""):
        # "" por si el payload viene sin event pero con content (tests)
        if event == "message_updated":
            logger.info("chatwoot_ignored_event", chatwoot_event=event)
            return {"status": "ignored", "reason": "message_updated"}
        if is_human_public_outgoing(payload):
            background_tasks.add_task(_process_human_outgoing, payload)
            return {"status": "ok", "queued": "true", "kind": "human_outgoing"}
        if _is_incoming_event(payload) or event == "":
            background_tasks.add_task(_process_incoming_message, payload)
            return {"status": "ok", "queued": "true"}
        logger.info("chatwoot_ignored_event", chatwoot_event=event or "unknown")
        return {"status": "ignored", "reason": "non_incoming"}

    logger.info("chatwoot_ignored_event", chatwoot_event=event or "unknown")
    return {"status": "ignored", "event": event or "unknown"}
