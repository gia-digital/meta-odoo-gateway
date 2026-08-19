"""Señales WhatsApp Cloud API (Meta): leído y escribiendo."""
from typing import Optional

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_API_VERSION = "v26.0"


def _whatsapp_cloud_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.chatwoot_enabled
        and settings.whatsapp_cloud_access_token.strip()
        and settings.whatsapp_cloud_phone_number_id.strip()
    )


def _graph_messages_url() -> Optional[str]:
    if not _whatsapp_cloud_configured():
        return None
    settings = get_settings()
    version = settings.whatsapp_cloud_api_version.strip() or DEFAULT_API_VERSION
    phone_id = settings.whatsapp_cloud_phone_number_id.strip()
    return f"https://graph.facebook.com/{version}/{phone_id}/messages"


async def signal_whatsapp_inbound(
    message_id: str,
    *,
    mark_read: bool = True,
    typing_indicator: bool = False,
) -> bool:
    """
    Marca un mensaje entrante como leído y/o muestra «escribiendo…» en WhatsApp.

    Meta permite combinar ambos en un solo POST (typing dura ~25 s o hasta responder).
    """
    if not message_id:
        return False
    url = _graph_messages_url()
    if not url:
        return False
    if not mark_read and not typing_indicator:
        return False

    payload: dict = {
        "messaging_product": "whatsapp",
        "message_id": message_id,
    }
    if mark_read:
        payload["status"] = "read"
    if typing_indicator:
        payload["typing_indicator"] = {"type": "text"}

    settings = get_settings()
    token = settings.whatsapp_cloud_access_token.strip()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code >= 400:
        logger.warning(
            "whatsapp_signal_failed",
            status=response.status_code,
            body=response.text[:300],
            message_id=message_id,
            mark_read=mark_read,
            typing_indicator=typing_indicator,
        )
        return False

    logger.info(
        "whatsapp_signal_sent",
        message_id=message_id,
        mark_read=mark_read,
        typing_indicator=typing_indicator,
    )
    return True


async def mark_whatsapp_message_read(message_id: str) -> bool:
    """Solo read receipt (p. ej. cuando un humano ya envió la respuesta)."""
    return await signal_whatsapp_inbound(
        message_id, mark_read=True, typing_indicator=False
    )
