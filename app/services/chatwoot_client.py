"""Cliente HTTP async para la API de Chatwoot (Agent Bot)."""
from typing import Any, Dict, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class ChatwootError(Exception):
    pass


class ChatwootClient:
    """Cliente del Agent Bot: enviar mensajes y handoff a humano."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "ChatwootClient":
        if not self.settings.chatwoot_base_url or not self.settings.chatwoot_bot_token:
            raise ChatwootError("CHATWOOT_BASE_URL and CHATWOOT_BOT_TOKEN are required")
        self._client = httpx.AsyncClient(
            base_url=self.settings.chatwoot_base_url.rstrip("/"),
            timeout=30.0,
            headers={
                "Content-Type": "application/json",
                "api_access_token": self.settings.chatwoot_bot_token,
            },
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client:
            await self._client.aclose()

    def _account_path(self, suffix: str) -> str:
        account_id = self.settings.chatwoot_account_id
        if not account_id:
            raise ChatwootError("CHATWOOT_ACCOUNT_ID is required")
        return f"/api/v1/accounts/{account_id}{suffix}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def send_message(
        self,
        conversation_id: int,
        content: str,
        *,
        private: bool = False,
    ) -> Dict[str, Any]:
        """POST outgoing message into a Chatwoot conversation."""
        assert self._client is not None
        url = self._account_path(f"/conversations/{conversation_id}/messages")
        payload = {
            "content": content,
            "message_type": "outgoing",
            "private": private,
        }
        r = await self._client.post(url, json=payload)
        if r.status_code >= 400:
            logger.error(
                "chatwoot_send_message_failed",
                status=r.status_code,
                body=r.text[:500],
                conversation_id=conversation_id,
            )
            raise ChatwootError(f"send_message failed: {r.status_code} {r.text[:300]}")
        data = r.json() if r.content else {}
        logger.info(
            "chatwoot_message_sent",
            conversation_id=conversation_id,
            message_id=data.get("id"),
        )
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def handoff_to_human(self, conversation_id: int) -> Dict[str, Any]:
        """
        Cambia status a open para que un agente humano tome la conversación.
        (Conversaciones con Agent Bot nacen en pending.)
        """
        assert self._client is not None
        url = self._account_path(f"/conversations/{conversation_id}/toggle_status")
        payload = {"status": "open"}
        r = await self._client.post(url, json=payload)
        if r.status_code >= 400:
            logger.error(
                "chatwoot_handoff_failed",
                status=r.status_code,
                body=r.text[:500],
                conversation_id=conversation_id,
            )
            raise ChatwootError(f"handoff failed: {r.status_code} {r.text[:300]}")
        data = r.json() if r.content else {}
        logger.info("chatwoot_handed_off", conversation_id=conversation_id)
        return data
