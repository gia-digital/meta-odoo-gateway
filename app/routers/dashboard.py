"""Dashboard HTML simple para revisar leads y conversaciones (antes de Odoo)."""
import hmac
import re
from calendar import monthrange
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.responses import Response as StarletteResponse

from app.core.config import get_settings
from app.models.conversation import Conversation, ConversationStatus
from app.models.db import get_db
from app.services.material_groups import group_material_label

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
COOKIE_MAX_AGE = 60 * 60 * 24 * 7
LEAD_STATUSES = (ConversationStatus.qualified, ConversationStatus.handed_off)
CHART_DAYS = 30
DEFAULT_PERIOD = "30d"
ALL_TIME_MONTHLY_THRESHOLD_DAYS = 62
ROLLING_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}
ROLLING_PERIOD_LABELS = {
    "7d": "Últimos 7 días",
    "30d": "Últimos 30 días",
    "90d": "Últimos 90 días",
}

MONTH_NAMES_ES = (
    "",
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
)


@dataclass(frozen=True)
class DashboardPeriod:
    key: str
    label: str
    start: date
    end: date
    bucket: str  # "day" | "month"
    anchor_end: Optional[date] = None


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


def _request_origin(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def is_dashboard_embed(request: Request) -> bool:
    """
    True si la petición viene de un iframe de Chatwoot (orígenes allowlist).

    Requiere Referer del origen permitido. Si el navegador envía Sec-Fetch-Dest,
    debe ser ``iframe`` (evita abrir el panel en pestaña nueva sin token).
    """
    allowed = get_settings().dashboard_embed_origins_list
    if not allowed:
        return False

    referer_origin = _request_origin(request.headers.get("referer"))
    if not referer_origin or referer_origin not in allowed:
        return False

    dest = (request.headers.get("sec-fetch-dest") or "").strip().lower()
    if dest and dest != "iframe":
        return False
    return True


def set_dashboard_auth_cookie(
    response: StarletteResponse, token: str, *, embed: bool
) -> None:
    """Cookie de sesión del dashboard. En iframe cross-origin hace falta SameSite=None."""
    kwargs: Dict[str, Any] = {
        "key": COOKIE_NAME,
        "value": token,
        "httponly": True,
        "max_age": COOKIE_MAX_AGE,
        "path": "/",
    }
    if embed:
        kwargs["samesite"] = "none"
        kwargs["secure"] = True
    else:
        kwargs["samesite"] = "lax"
        kwargs["secure"] = get_settings().app_env == "production"
    response.set_cookie(**kwargs)


def clear_dashboard_auth_cookie(response: StarletteResponse) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
    # Por si la sesión se creó embebida (SameSite=None; Secure).
    response.delete_cookie(COOKIE_NAME, path="/", samesite="none", secure=True)


def mark_embed_auth_cookie(request: Request) -> None:
    """Pide al middleware que fije la cookie tras la respuesta (navegación dentro del iframe)."""
    request.state.set_dashboard_embed_cookie = True


def _rel_path(request: Request, name: str, **path_params: Any) -> str:
    """Ruta relativa para redirects (evita Location http:// detrás de Caddy → mixed content)."""
    return request.url_for(name, **path_params).path


async def require_dashboard_auth(request: Request) -> None:
    _check_admin_ip(request)
    token = request.cookies.get(COOKIE_NAME)
    if _token_valid(token):
        return
    if is_dashboard_embed(request):
        mark_embed_auth_cookie(request)
        return
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": _rel_path(request, "dashboard_login")},
    )


def _lead_activity_date(value: Conversation) -> Optional[date]:
    dt = value.qualified_at or value.created_at
    if dt is None:
        return None
    return _aware(dt).astimezone(_display_tz()).date()


def _month_label(year: int, month: int, *, today: date) -> str:
    name = MONTH_NAMES_ES[month]
    if year == today.year and month == today.month:
        return f"Este mes ({name} {year})"
    return f"{name} {year}"


def _month_short(month: int) -> str:
    return MONTH_NAMES_ES[month][:3]


def _day_chart_label(value: date) -> str:
    return f"{value.day} {_month_short(value.month)}"


def _month_year_chart_label(year: int, month: int) -> str:
    return f"{MONTH_NAMES_ES[month]} {year}"


def _date_range_label(start: date, end: date) -> str:
    if start.year == end.year and start.month == end.month:
        month_name = MONTH_NAMES_ES[start.month]
        if start.day == end.day:
            return f"{start.day} de {month_name} de {start.year}"
        return f"{start.day}–{end.day} de {month_name} de {start.year}"
    if start.year == end.year:
        return (
            f"{start.day} {_month_short(start.month)} – "
            f"{end.day} {_month_short(end.month)} {end.year}"
        )
    return (
        f"{_day_chart_label(start)} {start.year} – "
        f"{_day_chart_label(end)} {end.year}"
    )


def _shift_month(year: int, month: int, delta: int) -> Tuple[int, int]:
    month += delta
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return year, month


def _parse_anchor_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _rolling_period(period_key: str, *, end: date, today: date) -> DashboardPeriod:
    days = ROLLING_PERIOD_DAYS[period_key]
    end_date = min(end, today)
    start = end_date - timedelta(days=days - 1)
    if end_date == today:
        label = ROLLING_PERIOD_LABELS[period_key]
        anchor_end = None
    else:
        label = f"{days} días · {_date_range_label(start, end_date)}"
        anchor_end = end_date
    return DashboardPeriod(
        period_key,
        label,
        start,
        end_date,
        "day",
        anchor_end=anchor_end,
    )


def period_query(period_key: str, *, anchor_end: Optional[date] = None) -> str:
    query = f"period={period_key}"
    if anchor_end and period_key in ROLLING_PERIOD_DAYS:
        query += f"&end={anchor_end.isoformat()}"
    return query


def period_overview_href(period_key: str, *, anchor_end: Optional[date] = None) -> str:
    return f"/dashboard/overview?{period_query(period_key, anchor_end=anchor_end)}"


def parse_dashboard_period(
    key: Optional[str],
    *,
    anchor_end: Optional[date] = None,
    now: Optional[datetime] = None,
) -> DashboardPeriod:
    """Interpreta el selector de periodo del resumen."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(_display_tz()).date()
    period_key = (key or DEFAULT_PERIOD).strip().lower()

    if period_key in ROLLING_PERIOD_DAYS:
        return _rolling_period(
            period_key,
            end=anchor_end or today,
            today=today,
        )
    if period_key == "all":
        return DashboardPeriod("all", "Todo el tiempo", today, today, "month")

    month_match = re.fullmatch(r"(\d{4})-(\d{2})", period_key)
    if month_match:
        year = int(month_match.group(1))
        month = int(month_match.group(2))
        if 1 <= month <= 12:
            start = date(year, month, 1)
            end = date(year, month, monthrange(year, month)[1])
            if end > today:
                end = today
            if start <= end:
                return DashboardPeriod(
                    period_key,
                    _month_label(year, month, today=today),
                    start,
                    end,
                    "day",
                )

    return parse_dashboard_period(DEFAULT_PERIOD, now=now)


def resolve_dashboard_period(
    period: DashboardPeriod,
    leads: Sequence[Conversation],
    *,
    now: Optional[datetime] = None,
) -> DashboardPeriod:
    """Ajusta límites dinámicos (p. ej. todo el tiempo)."""
    if period.key != "all":
        return period

    now = now or datetime.now(timezone.utc)
    today = now.astimezone(_display_tz()).date()
    dates = [d for d in (_lead_activity_date(c) for c in leads) if d]
    if not dates:
        return DashboardPeriod("all", period.label, today, today, "day")

    start = min(dates)
    end = max(dates)
    span_days = (end - start).days
    bucket = "month" if span_days > ALL_TIME_MONTHLY_THRESHOLD_DAYS else "day"
    return DashboardPeriod("all", period.label, start, end, bucket)


def build_period_choices(
    leads: Sequence[Conversation],
    *,
    selected: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(_display_tz()).date()
    months: Set[Tuple[int, int]] = set()
    for lead in leads:
        activity = _lead_activity_date(lead)
        if activity:
            months.add((activity.year, activity.month))

    quick = [
        {"value": "7d", "label": "Últimos 7 días"},
        {"value": "30d", "label": "Últimos 30 días"},
        {"value": "90d", "label": "Últimos 90 días"},
    ]
    month_options = [
        {
            "value": f"{year:04d}-{month:02d}",
            "label": _month_label(year, month, today=today),
        }
        for year, month in sorted(months, reverse=True)
    ]
    return {
        "quick": quick,
        "months": month_options,
        "selected": selected,
    }


def build_period_navigation(
    period: DashboardPeriod,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Enlaces para avanzar o retroceder un periodo."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(_display_tz()).date()

    if period.key == "all":
        return {"prev": None, "next": None}

    month_match = re.fullmatch(r"(\d{4})-(\d{2})", period.key)
    if month_match:
        year = int(month_match.group(1))
        month = int(month_match.group(2))
        prev_y, prev_m = _shift_month(year, month, -1)
        prev = {
            "href": period_overview_href(f"{prev_y:04d}-{prev_m:02d}"),
            "label": f"Anterior: {_month_label(prev_y, prev_m, today=today)}",
        }
        next_link = None
        next_y, next_m = _shift_month(year, month, 1)
        if (next_y, next_m) <= (today.year, today.month):
            next_link = {
                "href": period_overview_href(f"{next_y:04d}-{next_m:02d}"),
                "label": f"Siguiente: {_month_label(next_y, next_m, today=today)}",
            }
        return {"prev": prev, "next": next_link}

    if period.key in ROLLING_PERIOD_DAYS:
        days = ROLLING_PERIOD_DAYS[period.key]
        prev_end = period.start - timedelta(days=1)
        prev = {
            "href": period_overview_href(period.key, anchor_end=prev_end),
            "label": "Periodo anterior",
        }
        next_link = None
        if period.end < today:
            next_start = period.end + timedelta(days=1)
            next_end = min(next_start + timedelta(days=days - 1), today)
            next_link = {
                "href": period_overview_href(
                    period.key,
                    anchor_end=None if next_end >= today else next_end,
                ),
                "label": "Periodo siguiente",
            }
        return {"prev": prev, "next": next_link}

    return {"prev": None, "next": None}


def _lead_in_period(lead: Conversation, period: DashboardPeriod) -> bool:
    activity = _lead_activity_date(lead)
    if activity is None:
        return False
    return period.start <= activity <= period.end


def _chart_title(period: DashboardPeriod) -> str:
    if period.key in {"7d", "30d", "90d"}:
        return period.label
    if period.bucket == "month":
        return f"Prospectos por mes · {period.label.lower()}"
    if period.start.year == period.end.year and period.start.month == period.end.month:
        return _month_label(period.start.year, period.start.month, today=period.end)
    return _date_range_label(period.start, period.end)


def _iter_chart_buckets(period: DashboardPeriod) -> List[Tuple[str, str]]:
    buckets: List[Tuple[str, str]] = []
    if period.bucket == "day":
        cursor = period.start
        while cursor <= period.end:
            buckets.append((cursor.isoformat(), _day_chart_label(cursor)))
            cursor += timedelta(days=1)
        return buckets

    year, month = period.start.year, period.start.month
    end_year, end_month = period.end.year, period.end.month
    while (year, month) <= (end_year, end_month):
        buckets.append(
            (
                f"{year:04d}-{month:02d}",
                _month_year_chart_label(year, month),
            )
        )
        month += 1
        if month > 12:
            month = 1
            year += 1
    return buckets


def _bucket_key(period: DashboardPeriod, activity: date) -> str:
    if period.bucket == "day":
        return activity.isoformat()
    return f"{activity.year:04d}-{activity.month:02d}"


def build_lead_stats(
    leads: Sequence[Conversation],
    period: Optional[DashboardPeriod] = None,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Agrega KPIs y series para el dashboard de prospectos."""
    now = now or datetime.now(timezone.utc)
    requested = period or parse_dashboard_period(DEFAULT_PERIOD, now=now)
    period = resolve_dashboard_period(requested, leads, now=now)
    scoped = [c for c in leads if _lead_in_period(c, period)]

    total = len(scoped)
    period_days = max(1, (period.end - period.start).days + 1)
    avg_per_day = round(total / period_days, 1)

    qualified = sum(1 for c in scoped if c.status == ConversationStatus.qualified)
    handed_off = sum(1 for c in scoped if c.status == ConversationStatus.handed_off)

    with_material = sum(1 for c in scoped if (c.product_interest or "").strip())
    with_volume = sum(1 for c in scoped if (c.budget or "").strip())
    with_timeline = sum(1 for c in scoped if (c.timeline or "").strip())
    with_phone = sum(1 for c in scoped if (c.user_phone or "").strip())

    by_channel: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    materials: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()

    for c in scoped:
        by_channel[c.channel.value] += 1
        by_status[c.status.value] += 1
        by_source[c.qualification_source.value] += 1
        if c.product_interest and c.product_interest.strip():
            materials[group_material_label(c.product_interest)] += 1
        activity = _lead_activity_date(c)
        if activity:
            bucket_counts[_bucket_key(period, activity)] += 1

    chart_buckets = _iter_chart_buckets(period)
    day_labels = [label for _, label in chart_buckets]
    day_values = [bucket_counts.get(key, 0) for key, _ in chart_buckets]

    top_materials = materials.most_common(8)

    def pct(n: int) -> int:
        return round((n / total) * 100) if total else 0

    return {
        "total": total,
        "avg_per_day": avg_per_day,
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
        "chart_days": len(day_labels),
        "period_key": period.key,
        "period_label": period.label,
        "period_start": period.start.isoformat(),
        "period_end": period.end.isoformat(),
        "period_anchor_end": period.anchor_end.isoformat() if period.anchor_end else None,
        "chart_title": _chart_title(period),
    }


@router.get("", response_class=HTMLResponse, name="dashboard_login")
@router.get("/", response_class=HTMLResponse, name="dashboard_login_slash")
async def dashboard_login(request: Request):
    _check_admin_ip(request)
    token = request.cookies.get(COOKIE_NAME)
    if _token_valid(token):
        return RedirectResponse(
            url=_rel_path(request, "dashboard_overview"), status_code=303
        )
    if is_dashboard_embed(request):
        response = RedirectResponse(
            url=_rel_path(request, "dashboard_overview"), status_code=303
        )
        set_dashboard_auth_cookie(
            response, get_settings().admin_api_token, embed=True
        )
        return response
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
        url=_rel_path(request, "dashboard_overview"), status_code=303
    )
    set_dashboard_auth_cookie(
        response, token, embed=is_dashboard_embed(request)
    )
    return response


@router.post("/logout")
async def dashboard_logout(request: Request):
    response = RedirectResponse(
        url=_rel_path(request, "dashboard_login"), status_code=303
    )
    clear_dashboard_auth_cookie(response)
    return response


@router.get("/overview", response_class=HTMLResponse, name="dashboard_overview")
async def dashboard_overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
    period: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
):
    stmt = (
        select(Conversation)
        .where(Conversation.status.in_(LEAD_STATUSES))
        .order_by(Conversation.qualified_at.desc().nullslast())
    )
    result = await db.execute(stmt.limit(2000))
    leads = result.scalars().all()

    dashboard_period = parse_dashboard_period(period, anchor_end=_parse_anchor_date(end))
    stats = build_lead_stats(leads, dashboard_period)
    period_choices = build_period_choices(leads, selected=stats["period_key"])
    resolved_period = resolve_dashboard_period(dashboard_period, leads)
    period_nav = build_period_navigation(resolved_period)
    recent = [c for c in leads if _lead_in_period(c, resolved_period)][:8]

    return templates.TemplateResponse(
        "overview.html",
        {
            "request": request,
            "stats": stats,
            "period_choices": period_choices,
            "period_nav": period_nav,
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
            url=_rel_path(request, "dashboard_lead_detail", lead_id=conv.id),
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
