"""Seguridad: auth de leads y admin."""
import hmac
from typing import Optional

from fastapi import Header, HTTPException, Query, Request, status

from app.core.config import get_settings


async def require_lead_auth(
    request: Request,
    x_lead_token: Optional[str] = Header(default=None, alias="X-Lead-Token"),
    token: Optional[str] = Query(default=None),
) -> bytes:
    """
    Auth para POST /leads.

    Token compartido en cabecera X-Lead-Token o query ?token=.
    """
    body = await request.body()
    settings = get_settings()

    expected = settings.lead_webhook_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Lead webhook auth not configured (LEAD_WEBHOOK_TOKEN)",
        )

    provided = x_lead_token or token
    if (
        provided
        and len(provided) == len(expected)
        and hmac.compare_digest(provided, expected)
    ):
        return body

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid lead webhook credentials",
    )


async def require_admin_token(
    request: Request,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """Dependencia FastAPI para endpoints /admin."""
    settings = get_settings()

    if settings.admin_ips_list:
        client_ip = request.client.host if request.client else None
        if client_ip not in settings.admin_ips_list:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="IP not allowed"
            )

    if not x_admin_token or not hmac.compare_digest(
        x_admin_token, settings.admin_api_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token"
        )
