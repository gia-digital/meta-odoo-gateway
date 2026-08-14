"""Dashboard HTML simple para revisar leads y conversaciones (antes de Odoo)."""
import hmac
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.conversation import Conversation, ConversationStatus
from app.models.db import get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

STATUS_LABELS = {
    "active": "Activa",
    "qualified": "Calificado",
    "handed_off": "Escalado a ventas",
    "closed": "Cerrada",
}
CHANNEL_LABELS = {
    "whatsapp": "WhatsApp",
    "messenger": "Messenger",
    "instagram": "Instagram",
}
SOURCE_LABELS = {
    "none": "Sin fuente",
    "meta_agent": "Histórico (Meta)",
    "local_score": "Score local",
    "chatwoot_agent": "Chatwoot Agent Bot",
}
SIGNAL_LABELS = {
    "product_mentioned": "Material o línea de acero",
    "budget_mentioned": "Volumen / presupuesto",
    "urgency_signaled": "Urgencia de entrega",
    "decision_intent": "Intención de compra",
    "multiple_messages": "Conversación activa",
    "shared_contact": "Datos de contacto",
    "requested_human": "Pidió hablar con ventas",
}


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    return value.value if hasattr(value, "value") else str(value)


def label_status(value: Any) -> str:
    key = _enum_value(value)
    return STATUS_LABELS.get(key, key.replace("_", " ").capitalize() if key else "—")


def label_channel(value: Any) -> str:
    key = _enum_value(value)
    return CHANNEL_LABELS.get(key, key.capitalize() if key else "—")


def label_source(value: Any) -> str:
    key = _enum_value(value)
    return SOURCE_LABELS.get(key, key.replace("_", " ") if key else "—")


def label_signal(value: Any) -> str:
    key = _enum_value(value)
    if key in SIGNAL_LABELS:
        return SIGNAL_LABELS[key]
    return key.replace("_", " ").capitalize() if key else "—"


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _display_tz() -> ZoneInfo:
    name = get_settings().display_timezone or "America/Mexico_City"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def format_dt(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, datetime):
        return _aware(value).astimezone(_display_tz()).strftime("%d/%m/%Y %H:%M")
    return str(value)


def truncate(value: Any, length: int = 80) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return "—"
    if len(text) <= length:
        return text
    return text[: max(0, length - 1)].rstrip() + "…"


templates.env.filters["label_status"] = label_status
templates.env.filters["label_channel"] = label_channel
templates.env.filters["label_source"] = label_source
templates.env.filters["label_signal"] = label_signal
templates.env.filters["format_dt"] = format_dt
templates.env.filters["truncate_text"] = truncate

router = APIRouter(prefix="/dashboard", tags=["dashboard"], include_in_schema=False)

COOKIE_NAME = "dashboard_token"
LEAD_STATUSES = (ConversationStatus.qualified, ConversationStatus.handed_off)
CHART_DAYS = 30


def _check_admin_ip(request: Request) -> None:
    settings = get_settings()
    if settings.admin_ips_list:
        client_ip = request.client.host if request.client else None
        if client_ip not in settings.admin_ips_list:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="IP not allowed"
            )


def _token_valid(token: Optional[str]) -> bool:
    if not token:
        return False
    settings = get_settings()
    return hmac.compare_digest(token, settings.admin_api_token)


async def require_dashboard_auth(request: Request) -> None:
    _check_admin_ip(request)
    token = request.cookies.get(COOKIE_NAME)
    if not _token_valid(token):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": str(request.url_for("dashboard_login"))},
        )


def _as_utc_date(value: Optional[datetime]) -> Optional[date]:
    if value is None:
        return None
    return _aware(value).date()


def build_lead_stats(leads: Sequence[Conversation]) -> Dict[str, Any]:
    """Agrega KPIs y series para el dashboard de prospectos."""
    total = len(leads)
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=CHART_DAYS)

    qualified = sum(1 for c in leads if c.status == ConversationStatus.qualified)
    handed_off = sum(1 for c in leads if c.status == ConversationStatus.handed_off)
    this_week = sum(
        1 for c in leads if c.qualified_at and _aware(c.qualified_at) >= week_ago
    )

    with_material = sum(1 for c in leads if (c.product_interest or "").strip())
    with_volume = sum(1 for c in leads if (c.budget or "").strip())
    with_timeline = sum(1 for c in leads if (c.timeline or "").strip())
    with_phone = sum(1 for c in leads if (c.user_phone or "").strip())

    by_channel: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    materials: Counter[str] = Counter()
    daily: Counter[str] = Counter()

    for c in leads:
        by_channel[c.channel.value] += 1
        by_status[c.status.value] += 1
        by_source[c.qualification_source.value] += 1
        if c.product_interest and c.product_interest.strip():
            materials[c.product_interest.strip()] += 1
        qday = _as_utc_date(c.qualified_at) or _as_utc_date(c.created_at)
        if qday and qday >= month_ago.date():
            daily[qday.isoformat()] += 1

    day_labels: List[str] = []
    day_values: List[int] = []
    for i in range(CHART_DAYS - 1, -1, -1):
        d = (now - timedelta(days=i)).date()
        day_labels.append(d.strftime("%d/%m"))
        day_values.append(daily.get(d.isoformat(), 0))

    top_materials = materials.most_common(8)

    def pct(n: int) -> int:
        return round((n / total) * 100) if total else 0

    return {
        "total": total,
        "this_week": this_week,
        "qualified": qualified,
        "handed_off": handed_off,
        "with_material": with_material,
        "with_volume": with_volume,
        "with_timeline": with_timeline,
        "with_phone": with_phone,
        "pct_material": pct(with_material),
        "pct_volume": pct(with_volume),
        "pct_timeline": pct(with_timeline),
        "pct_phone": pct(with_phone),
        "pct_handed_off": pct(handed_off),
        "channel_labels": [CHANNEL_LABELS.get(k, k) for k, _ in by_channel.most_common()],
        "channel_values": [v for _, v in by_channel.most_common()],
        "status_labels": [STATUS_LABELS.get(k, k) for k, _ in by_status.most_common()],
        "status_values": [v for _, v in by_status.most_common()],
        "source_labels": [SOURCE_LABELS.get(k, k) for k, _ in by_source.most_common()],
        "source_values": [v for _, v in by_source.most_common()],
        "material_labels": [m for m, _ in top_materials] or ["Sin datos"],
        "material_values": [v for _, v in top_materials] or [0],
        "day_labels": day_labels,
        "day_values": day_values,
        "chart_days": CHART_DAYS,
    }


@router.get("", response_class=HTMLResponse, name="dashboard_login")
@router.get("/", response_class=HTMLResponse, name="dashboard_login_slash")
async def dashboard_login(request: Request):
    _check_admin_ip(request)
    token = request.cookies.get(COOKIE_NAME)
    if _token_valid(token):
        return RedirectResponse(
            url=str(request.url_for("dashboard_overview")), status_code=303
        )
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None},
    )


@router.post("/login", response_class=HTMLResponse)
async def dashboard_login_post(
    request: Request,
    token: str = Form(...),
):
    _check_admin_ip(request)
    if not _token_valid(token):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Token incorrecto"},
            status_code=401,
        )
    response = RedirectResponse(
        url=str(request.url_for("dashboard_overview")), status_code=303
    )
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )
    return response


@router.post("/logout")
async def dashboard_logout(request: Request):
    response = RedirectResponse(
        url=str(request.url_for("dashboard_login")), status_code=303
    )
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/overview", response_class=HTMLResponse, name="dashboard_overview")
async def dashboard_overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    stmt = (
        select(Conversation)
        .where(Conversation.status.in_(LEAD_STATUSES))
        .order_by(Conversation.qualified_at.desc().nullslast())
    )
    result = await db.execute(stmt.limit(2000))
    leads = result.scalars().all()
    stats = build_lead_stats(leads)

    recent = leads[:8]

    return templates.TemplateResponse(
        "overview.html",
        {
            "request": request,
            "stats": stats,
            "recent_leads": recent,
            "active_nav": "overview",
        },
    )


@router.get("/leads", response_class=HTMLResponse, name="dashboard_leads")
async def dashboard_leads(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
    channel: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
):
    stmt = (
        select(Conversation)
        .where(Conversation.status.in_(LEAD_STATUSES))
        .order_by(Conversation.qualified_at.desc().nullslast(), Conversation.updated_at.desc())
    )
    if channel:
        stmt = stmt.where(Conversation.channel == channel)
    if status_filter:
        try:
            st = ConversationStatus(status_filter)
            stmt = stmt.where(Conversation.status == st)
        except ValueError:
            pass

    result = await db.execute(stmt.limit(200))
    conversations = result.scalars().all()
    return templates.TemplateResponse(
        "leads.html",
        {
            "request": request,
            "conversations": conversations,
            "channel": channel or "",
            "status_filter": status_filter or "",
            "active_nav": "leads",
        },
    )


@router.get(
    "/leads/{lead_id}",
    response_class=HTMLResponse,
    name="dashboard_lead_detail",
)
async def dashboard_lead_detail(
    lead_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    stmt = (
        select(Conversation)
        .where(Conversation.id == lead_id)
        .options(selectinload(Conversation.messages))
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv or conv.status not in LEAD_STATUSES:
        raise HTTPException(status_code=404, detail="Lead no encontrado")

    messages = sorted(conv.messages, key=lambda m: m.created_at or datetime.min)
    signals = (conv.score_breakdown or {}).get("signals", [])

    return templates.TemplateResponse(
        "lead_detail.html",
        {
            "request": request,
            "lead": conv,
            "messages": messages,
            "signals": signals,
            "active_nav": "leads",
        },
    )


@router.get("/conversations", response_class=HTMLResponse, name="dashboard_conversations")
async def dashboard_conversations(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
    channel: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
):
    stmt = select(Conversation).order_by(Conversation.updated_at.desc())
    if channel:
        stmt = stmt.where(Conversation.channel == channel)
    if status_filter:
        try:
            st = ConversationStatus(status_filter)
            stmt = stmt.where(Conversation.status == st)
        except ValueError:
            pass

    result = await db.execute(stmt.limit(200))
    conversations = result.scalars().all()
    return templates.TemplateResponse(
        "conversations.html",
        {
            "request": request,
            "conversations": conversations,
            "channel": channel or "",
            "status_filter": status_filter or "",
            "active_nav": "conversations",
        },
    )


@router.get(
    "/conversations/{conv_id}",
    response_class=HTMLResponse,
    name="dashboard_conversation_detail",
)
async def dashboard_conversation_detail(
    conv_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    stmt = (
        select(Conversation)
        .where(Conversation.id == conv_id)
        .options(selectinload(Conversation.messages))
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")

    # Si es un lead, preferir la ficha de lead
    if conv.status in LEAD_STATUSES:
        return RedirectResponse(
            url=str(request.url_for("dashboard_lead_detail", lead_id=conv.id)),
            status_code=303,
        )

    messages = sorted(conv.messages, key=lambda m: m.created_at or datetime.min)
    signals = (conv.score_breakdown or {}).get("signals", [])

    return templates.TemplateResponse(
        "conversation_detail.html",
        {
            "request": request,
            "conversation": conv,
            "messages": messages,
            "signals": signals,
            "active_nav": "conversations",
        },
    )
