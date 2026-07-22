"""Dashboard HTML simple para revisar leads y conversaciones (antes de Odoo)."""
import hmac
from datetime import datetime
from pathlib import Path
from typing import Optional

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

router = APIRouter(prefix="/dashboard", tags=["dashboard"], include_in_schema=False)

COOKIE_NAME = "dashboard_token"
LEAD_STATUSES = (ConversationStatus.qualified, ConversationStatus.handed_off)


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


@router.get("", response_class=HTMLResponse, name="dashboard_login")
@router.get("/", response_class=HTMLResponse, name="dashboard_login_slash")
async def dashboard_login(request: Request):
    _check_admin_ip(request)
    token = request.cookies.get(COOKIE_NAME)
    if _token_valid(token):
        return RedirectResponse(
            url=str(request.url_for("dashboard_leads")), status_code=303
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
        url=str(request.url_for("dashboard_leads")), status_code=303
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
