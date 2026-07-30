"""Seguridad: verificación de firma de Meta y auth de admin."""
import hmac
import hashlib
from typing import Optional

from fastapi import Header, HTTPException, Query, Request, status

from app.core.config import get_settings


def verify_meta_signature(payload: bytes, signature_header: Optional[str]) -> bool:
    """
    Verifica la firma HMAC SHA-256 que Meta incluye en cada webhook.
    Cabecera: X-Hub-Signature-256: sha256=<hex>
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    settings = get_settings()
    expected_signature = hmac.new(
        key=settings.meta_app_secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()

    received_signature = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected_signature, received_signature)


async def require_meta_signature(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(
        default=None, alias="X-Hub-Signature-256"
    ),
) -> bytes:
    """
    Dependencia FastAPI: lee el body crudo y valida la firma.
    Devuelve el body para que el handler lo deserialice.
    """
    body = await request.body()
    if not verify_meta_signature(body, x_hub_signature_256):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Meta webhook signature",
        )
    return body


async def require_meta_lead_auth(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(
        default=None, alias="X-Hub-Signature-256"
    ),
    x_meta_lead_token: Optional[str] = Header(
        default=None, alias="X-Meta-Lead-Token"
    ),
    token: Optional[str] = Query(default=None),
) -> bytes:
    """
    Auth para POST /leads y POST /webhook/meta/lead.

    Acepta:
    1. Firma Graph X-Hub-Signature-256 (si Meta envía el body firmado), o
    2. Token compartido en cabecera X-Meta-Lead-Token o query ?token=
    """
    body = await request.body()
    settings = get_settings()

    if x_hub_signature_256 and verify_meta_signature(body, x_hub_signature_256):
        return body

    expected = settings.meta_lead_webhook_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Lead webhook auth not configured (META_LEAD_WEBHOOK_TOKEN)",
        )

    provided = x_meta_lead_token or token
    if provided and hmac.compare_digest(provided, expected):
        return body

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid Meta lead webhook credentials",
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
