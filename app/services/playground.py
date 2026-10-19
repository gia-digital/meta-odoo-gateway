"""Turno de prueba del agente: mismo cerebro, sin guardar ni escribir en Chatwoot."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_behavior import get_agent_behavior
from app.core.config import get_settings
from app.models.conversation import (
    Channel,
    Conversation,
    ConversationStatus,
    QualificationSource,
)
from app.services.gia_agent import BotContext, run_gia_agent
from app.services.reply_bubbles import split_reply_bubbles

HISTORY_LIMIT = 40
CONTENT_LIMIT = 8000
MESSAGE_LIMIT = 4000


def sanitize_history(raw: Any) -> List[Dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, str]] = []
    for item in raw[-HISTORY_LIMIT:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in ("user", "assistant"):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        out.append({"role": role, "content": content[:CONTENT_LIMIT]})
    return out


def _opt_text(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def conversation_from_state(state: Any) -> Conversation:
    data = state if isinstance(state, dict) else {}
    status_raw = str(data.get("status") or "active")
    try:
        status = ConversationStatus(status_raw)
    except ValueError:
        status = ConversationStatus.active
    handed_off = bool(data.get("handed_off")) or status == ConversationStatus.handed_off
    if handed_off:
        status = ConversationStatus.handed_off
    now = datetime.now(timezone.utc)
    conv = Conversation(
        id=0,
        channel=Channel.whatsapp,
        external_user_id="playground",
        user_name=_opt_text(data.get("user_name"), 255),
        user_phone=_opt_text(data.get("user_phone"), 64),
        user_email=_opt_text(data.get("user_email"), 255),
        status=status,
        score=0,
        score_breakdown={},
        qualification_source=QualificationSource.none,
        qualification_reason=_opt_text(data.get("qualification_reason"), 4000),
        product_interest=_opt_text(data.get("product_interest"), 255),
        lead_summary=_opt_text(data.get("lead_summary"), 4000),
        budget=_opt_text(data.get("budget"), 255),
        timeline=_opt_text(data.get("timeline"), 255),
        preferred_contact_time=_opt_text(data.get("preferred_contact_time"), 255),
    )
    if status in (ConversationStatus.qualified, ConversationStatus.handed_off):
        conv.qualified_at = now
    if handed_off:
        conv.handed_off_at = now
    return conv


def state_from_context(ctx: BotContext) -> Dict[str, Any]:
    conv = ctx.conversation
    status = conv.status.value if hasattr(conv.status, "value") else str(conv.status)
    return {
        "status": status,
        "handed_off": bool(ctx.handed_off or status == ConversationStatus.handed_off.value),
        "product_interest": conv.product_interest,
        "budget": conv.budget,
        "timeline": conv.timeline,
        "lead_summary": conv.lead_summary,
        "qualification_reason": conv.qualification_reason,
        "preferred_contact_time": conv.preferred_contact_time,
        "user_name": conv.user_name,
        "user_phone": conv.user_phone,
        "user_email": conv.user_email,
        "catalog_sent": bool(ctx.extra.get("catalog_sent")),
    }


async def run_playground_turn(
    db: AsyncSession,
    *,
    message: str,
    history: Any = None,
    state: Any = None,
) -> Dict[str, Any]:
    text = (message or "").strip()
    if not text:
        raise ValueError("empty message")
    text = text[:MESSAGE_LIMIT]
    conv = conversation_from_state(state)
    prior = sanitize_history(history)
    ctx = BotContext(
        db=db,
        conversation=conv,
        channel=Channel.whatsapp,
        external_user_id="playground",
        chatwoot_conversation_id=0,
        user_name=conv.user_name,
        user_phone=conv.user_phone,
        user_email=conv.user_email,
        handed_off=conv.status == ConversationStatus.handed_off,
        sandbox=True,
    )
    reply = await run_gia_agent(
        ctx=ctx,
        user_message=text,
        history_messages=prior,
    )
    behavior = await get_agent_behavior(db)
    cap = behavior.reply_max_bubbles or get_settings().chatwoot_reply_max_bubbles
    bubbles = split_reply_bubbles(reply, max_bubbles=cap) or [reply]
    events = list(ctx.extra.get("playground_events") or [])
    return {
        "reply": reply,
        "bubbles": bubbles,
        "events": events,
        "state": state_from_context(ctx),
    }
