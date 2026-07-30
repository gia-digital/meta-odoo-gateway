"""
Webhook de Meta (WhatsApp + Messenger).

- GET  /webhook/meta       — verificación
- POST /webhook/meta       — mensajes + handovers
- POST /webhook/meta/lead  — lead calificado por Meta Business Agent
"""
import json
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import require_meta_lead_auth, require_meta_signature
from app.models.conversation import Channel
from app.models.db import get_db
from app.models.schemas import (
    LeadCreate,
    MetaLeadPayload,
    NormalizedHandover,
    NormalizedMessage,
)
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
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed"
    )


# ============================================================
# POST: recepción de eventos (mensajes + handovers)
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
    """
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    obj = payload.get("object")
    entries = payload.get("entry", [])

    normalized_messages: List[NormalizedMessage] = []
    handovers: List[NormalizedHandover] = []

    if obj == "whatsapp_business_account":
        normalized_messages = _parse_whatsapp_entries(entries)
        handovers = _parse_whatsapp_handovers(entries)
    elif obj == "page":
        normalized_messages = _parse_messenger_entries(entries)
        handovers = _parse_messenger_handovers(entries, channel="messenger")
    elif obj == "instagram":
        normalized_messages = _parse_messenger_entries(entries, channel="instagram")
        handovers = _parse_messenger_handovers(entries, channel="instagram")
    else:
        logger.warning("unknown_webhook_object", object=obj)
        return {"status": "ignored"}

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

    for ho in handovers:
        try:
            channel_enum = Channel(ho.channel)
        except ValueError:
            logger.warning("handover_unknown_channel", channel=ho.channel)
            continue
        conv = await service.get_or_create(
            channel=channel_enum,
            external_user_id=ho.external_user_id,
        )
        await service.qualify_from_meta(
            conv,
            reason=ho.reason or "Meta messaging handover",
            handed_off=True,
            metadata={"raw_event": "messaging_handover"},
        )

    return {"status": "ok"}


# ============================================================
# POST: lead calificado por Meta Agent
# ============================================================


@router.post("/meta/lead", status_code=200)
async def receive_meta_lead(
    request: Request,
    body: bytes = Depends(require_meta_lead_auth),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Alias legacy de POST /leads.
    Preferir POST /leads como tool del Meta Business Agent.
    """
    from app.routers.leads import create_lead_from_create, lead_to_out

    try:
        raw = json.loads(body) if body else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Aceptar payload plano o envuelto en { "lead": {...} }
    if isinstance(raw.get("lead"), dict):
        raw = raw["lead"]

    try:
        # MetaLeadPayload acepta metadata extra; LeadCreate es el contrato tool
        payload = MetaLeadPayload.model_validate(raw)
        lead = LeadCreate(
            channel=payload.channel,
            external_user_id=payload.external_user_id,
            user_name=payload.user_name,
            user_phone=payload.user_phone,
            user_email=payload.user_email,
            reason=payload.reason,
            summary=payload.summary or (payload.metadata or {}).get("summary"),
            product_interest=payload.product_interest
            or (payload.metadata or {}).get("product_interest"),
            budget=payload.budget or (payload.metadata or {}).get("budget"),
            timeline=payload.timeline or (payload.metadata or {}).get("timeline"),
            preferred_contact_time=payload.preferred_contact_time
            or (payload.metadata or {}).get("preferred_contact_time"),
            handed_off=payload.handed_off,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid lead payload: {exc}") from exc

    conv = await create_lead_from_create(db, lead)
    out = lead_to_out(conv)
    return {
        "status": "ok",
        "conversation_id": out.id,
        "conversation_status": out.status,
        "qualification_source": out.qualification_source,
        "lead": out.model_dump(mode="json"),
    }


# ============================================================
# Parseo: WhatsApp
# ============================================================


def _parse_whatsapp_entries(entries: List[Dict[str, Any]]) -> List[NormalizedMessage]:
    out: List[NormalizedMessage] = []
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", []) or []
            contacts = value.get("contacts", []) or []
            contact_by_id = {c.get("wa_id"): c for c in contacts if c.get("wa_id")}

            for m in messages:
                if m.get("type") != "text":
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


def _parse_whatsapp_handovers(entries: List[Dict[str, Any]]) -> List[NormalizedHandover]:
    """
    WhatsApp Cloud API `messaging_handovers` (v25+/v26):

        changes[].field == "messaging_handovers"
        changes[].value.sender.phone_number  -> usuario
        changes[].value.control_passed.metadata -> motivo

    También acepta formas legacy (from / wa_id / contacts).
    """
    out: List[NormalizedHandover] = []
    control_keys = (
        "control_passed",
        "control_taken",
        "control_requested",
        "request_welcome",
    )

    for entry in entries:
        for change in entry.get("changes", []):
            field = change.get("field", "")
            value = change.get("value", {}) or {}

            if field not in ("messaging_handovers", "handover", "thread_control"):
                continue

            sender = value.get("sender") or {}
            user_id = (
                sender.get("phone_number")
                or value.get("recipient_id")
                or value.get("from")
                or value.get("wa_id")
                or (value.get("contacts") or [{}])[0].get("wa_id")
            )
            if not user_id:
                logger.warning("whatsapp_handover_missing_user", field=field)
                continue

            reason = _whatsapp_handover_reason(value, field, control_keys)

            out.append(
                NormalizedHandover(
                    channel="whatsapp",
                    external_user_id=str(user_id),
                    reason=str(reason) if reason else None,
                    raw=change,
                )
            )
    return out


def _whatsapp_handover_reason(
    value: Dict[str, Any], field: str, control_keys: tuple
) -> str:
    for key in control_keys:
        ctrl = value.get(key)
        if not isinstance(ctrl, dict):
            continue
        meta = ctrl.get("metadata")
        if isinstance(meta, str) and meta:
            return meta
        if isinstance(meta, dict) and meta.get("reason"):
            return str(meta["reason"])
        if ctrl.get("reason"):
            return str(ctrl["reason"])
        return f"WhatsApp {key}"

    meta = value.get("metadata")
    if isinstance(meta, str) and meta:
        return meta
    if isinstance(meta, dict) and meta.get("reason"):
        return str(meta["reason"])
    if value.get("reason"):
        return str(value["reason"])
    return f"WhatsApp {field}"


# ============================================================
# Parseo: Messenger (e Instagram)
# ============================================================


def _parse_messenger_entries(
    entries: List[Dict[str, Any]], channel: str = "messenger"
) -> List[NormalizedMessage]:
    out: List[NormalizedMessage] = []
    for entry in entries:
        for event in entry.get("messaging", []):
            message = event.get("message")
            if not message:
                continue
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


def _parse_messenger_handovers(
    entries: List[Dict[str, Any]], channel: str = "messenger"
) -> List[NormalizedHandover]:
    """
    Messenger: pass_thread_control / take_thread_control / request_thread_control
    en entry[].messaging[].
    """
    out: List[NormalizedHandover] = []
    handover_keys = (
        "pass_thread_control",
        "take_thread_control",
        "request_thread_control",
        "messaging_handovers",
    )
    for entry in entries:
        for event in entry.get("messaging", []):
            for key in handover_keys:
                if key not in event:
                    continue
                # El usuario suele estar en sender (cliente) o recipient
                sender = (event.get("sender") or {}).get("id")
                recipient = (event.get("recipient") or {}).get("id")
                # En pass_thread_control el sender es quien cede; el hilo es del usuario
                user_id = sender or recipient
                ctrl = event.get(key) or {}
                reason = (
                    ctrl.get("metadata")
                    or ctrl.get("reason")
                    or f"Messenger {key}"
                )
                if user_id:
                    out.append(
                        NormalizedHandover(
                            channel=channel,
                            external_user_id=str(user_id),
                            reason=str(reason) if reason else None,
                            raw=event,
                        )
                    )
    return out
