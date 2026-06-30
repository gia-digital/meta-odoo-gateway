"""Cliente para enviar mensajes a través de la Graph API de Meta."""
from typing import Any, Dict, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MetaClient:
    """
    Wrapper de la Graph API.
    Aunque Meta Business Agent normalmente envía las respuestas automáticamente,
    necesitamos este cliente para:
    - Enviar mensajes manuales tras el handoff
    - Enviar plantillas de WhatsApp
    - Marcar mensajes como leídos
    - Notificaciones programáticas
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "MetaClient":
        self._client = httpx.AsyncClient(
            base_url=self.settings.graph_base_url,
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {self.settings.meta_access_token}",
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client:
            await self._client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def send_whatsapp_text(self, to: str, text: str) -> Dict[str, Any]:
        """Envía un mensaje de texto por WhatsApp."""
        assert self._client is not None
        url = f"/{self.settings.whatsapp_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        r = await self._client.post(url, json=payload)
        r.raise_for_status()
        logger.info("whatsapp_message_sent", to=to, preview=text[:60])
        return r.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def send_messenger_text(self, recipient_psid: str, text: str) -> Dict[str, Any]:
        """Envía un mensaje a Messenger por PSID (Page-Scoped ID)."""
        assert self._client is not None
        url = f"/{self.settings.messenger_page_id}/messages"
        payload = {
            "recipient": {"id": recipient_psid},
            "message": {"text": text},
            "messaging_type": "RESPONSE",
        }
        r = await self._client.post(url, json=payload)
        r.raise_for_status()
        logger.info("messenger_message_sent", to=recipient_psid, preview=text[:60])
        return r.json()

    async def mark_whatsapp_as_read(self, message_id: str) -> None:
        """Marca un mensaje de WhatsApp como leído (mejor UX)."""
        assert self._client is not None
        url = f"/{self.settings.whatsapp_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        try:
            r = await self._client.post(url, json=payload)
            r.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("mark_read_failed", error=str(e), message_id=message_id)
