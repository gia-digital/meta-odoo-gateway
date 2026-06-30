"""
Webhook de Meta (WhatsApp + Messenger).

Dos endpoints en la misma ruta /webhook/meta:
- GET: verificación inicial cuando configuras el webhook en Meta
- POST: recepción de eventos (mensajes, status updates, etc.)
"""
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import require_meta_signature
from app.models.conversation import Channel
from app.models.db import get_db
from app.models.schemas import NormalizedMessage
from app.services.conversation import ConversationService

logger = get_logger(__name__)
router = APIRouter(prefix="/webhook", tags=["meta"])


# ============================================================
# GET: verificación del webhook
# ============================================================


@router.get("/meta")
async def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
) -> PlainTextResponse:
    settings = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        logger.info("webhook_verified")
        return PlainTextResponse(content=hub_challenge, status_code=200)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed")


# ============================================================
# POST: recepción de eventos
# ============================================================


@router.post("/meta", status_code=200)
async def receive_webhook(
    request: Request,
    body: bytes = Depends(require_meta_signature),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """
    Procesa eventos de WhatsApp Business y Messenger.

    Meta espera respuesta 200 OK rápida (<10s) o reintenta.
    Para procesamientos pesados se podría diferir a una cola (Celery, Arq),
    pero el flujo actual es lo suficientemente rápido para responder sincrónicamente.
    """
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    obj = payload.get("object")
    entries = payload.get("entry", [])

    normalized_messages: List[NormalizedMessage] = []

    if obj == "whatsapp_business_account":
        normalized_messages = _parse_whatsapp_entries(entries)
    elif obj == "page":
        normalized_messages = _parse_messenger_entries(entries)
    elif obj == "instagram":
        # Estructura similar a Messenger
        normalized_messages = _parse_messenger_entries(entries, channel="instagram")
    else:
        logger.warning("unknown_webhook_object", object=obj)
        return {"status": "ignored"}

    if not normalized_messages:
        # status updates, deliveries, reads, etc. — no son mensajes
        return {"status": "ok"}

    service = ConversationService(db)

    for nm in normalized_messages:
        channel_enum = Channel(nm.channel)
        conv = await service.get_or_create(
            channel=channel_enum,
            external_user_id=nm.external_user_id,
            user_name=nm.user_name,
        )
        await service.add_inbound_message(conv, nm)
        await service.process_after_message(conv)

    return {"status": "ok"}


# ============================================================
# Parseo: WhatsApp
# ============================================================


def _parse_whatsapp_entries(entries: List[Dict[str, Any]]) -> List[NormalizedMessage]:
    """
    Estructura de WhatsApp:
    entry[].changes[].value.messages[] + value.contacts[]
    """
    out: List[NormalizedMessage] = []
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", []) or []
            contacts = value.get("contacts", []) or []

            # Mapear contactos por wa_id
            contact_by_id = {c.get("wa_id"): c for c in contacts if c.get("wa_id")}

            for m in messages:
                if m.get("type") != "text":
                    # Por ahora solo texto. Audio/imagen/etc. se podrían agregar.
                    logger.info("non_text_message_skipped", type=m.get("type"))
                    continue

                from_id = m.get("from", "")
                text = m.get("text", {}).get("body", "")
                msg_id = m.get("id")

                contact = contact_by_id.get(from_id, {})
                profile = contact.get("profile", {}) or {}
                user_name = profile.get("name")

                out.append(
                    NormalizedMessage(
                        channel="whatsapp",
                        external_user_id=from_id,
                        external_message_id=msg_id,
                        user_name=user_name,
                        user_phone=from_id,
                        text=text,
                        raw=m,
                    )
                )
    return out


# ============================================================
# Parseo: Messenger (e Instagram, mismo schema)
# ============================================================


def _parse_messenger_entries(
    entries: List[Dict[str, Any]], channel: str = "messenger"
) -> List[NormalizedMessage]:
    """
    Estructura de Messenger:
    entry[].messaging[].message.text + sender.id (PSID)
    """
    out: List[NormalizedMessage] = []
    for entry in entries:
        for event in entry.get("messaging", []):
            message = event.get("message")
            if not message:
                continue
            # Echo de nuestros propios envíos — ignorar
            if message.get("is_echo"):
                continue
            text = message.get("text")
            if not text:
                continue
            sender_id = event.get("sender", {}).get("id")
            if not sender_id:
                continue
            out.append(
                NormalizedMessage(
                    channel=channel,
                    external_user_id=sender_id,
                    external_message_id=message.get("mid"),
                    text=text,
                    raw=event,
                )
            )
    return out
