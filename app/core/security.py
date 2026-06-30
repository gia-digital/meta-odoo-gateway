"""Seguridad: verificación de firma de Meta y auth de admin."""
import hashlib
import hmac
from typing import Optional

from fastapi import Header, HTTPException, Request, status

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
    x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
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


async def require_admin_token(
    request: Request,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """Dependencia FastAPI para endpoints /admin."""
    settings = get_settings()

    # IP allowlist (opcional)
    if settings.admin_ips_list:
        client_ip = request.client.host if request.client else None
        if client_ip not in settings.admin_ips_list:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP not allowed")

    if not x_admin_token or not hmac.compare_digest(x_admin_token, settings.admin_api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
