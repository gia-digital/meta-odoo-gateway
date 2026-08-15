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
    async def set_status(self, conversation_id: int, status: str) -> Dict[str, Any]:
        assert self._client is not None
        url = self._account_path(f"/conversations/{conversation_id}/toggle_status")
        r = await self._client.post(url, json={"status": status})
        if r.status_code >= 400:
            logger.error(
                "chatwoot_set_status_failed",
                status=r.status_code,
                body=r.text[:500],
                conversation_id=conversation_id,
                target=status,
            )
            raise ChatwootError(f"set_status failed: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    async def fetch_conversation(self, conversation_id: int) -> Dict[str, Any]:
        assert self._client is not None
        url = self._account_path(f"/conversations/{conversation_id}")
        r = await self._client.get(url)
        if r.status_code >= 400:
            raise ChatwootError(
                f"fetch_conversation failed: {r.status_code} {r.text[:300]}"
            )
        data = r.json() if r.content else {}
        if isinstance(data, dict) and isinstance(data.get("payload"), dict):
            return data["payload"]
        return data if isinstance(data, dict) else {}

    async def return_to_pending_if_unassigned(self, conversation_id: int) -> bool:
        """Vuelve a pending solo si sigue open y sin agente humano."""
        from app.services.chatwoot_payload import human_assignee_name

        data = await self.fetch_conversation(conversation_id)
        status = str(data.get("status") or "").lower()
        if status != "open":
            return False
        if human_assignee_name(data):
            logger.info(
                "chatwoot_resume_skipped_assigned",
                conversation_id=conversation_id,
            )
            return False
        await self.set_status(conversation_id, "pending")
        logger.info("chatwoot_returned_to_pending", conversation_id=conversation_id)
        return True

    async def handoff_to_human(
        self, conversation_id: int, *, note: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Cambia status a open para que un agente humano tome la conversación.
        (Conversaciones con Agent Bot nacen en pending.)
        """
        data = await self.set_status(conversation_id, "open")
        logger.info("chatwoot_handed_off", conversation_id=conversation_id)
        if note:
            try:
                await self.send_message(conversation_id, note, private=True)
            except Exception as exc:
                logger.error(
                    "chatwoot_handoff_note_failed",
                    conversation_id=conversation_id,
                    error=str(exc),
                )
        from app.services.turn_guard import schedule_handoff_resume

        schedule_handoff_resume(conversation_id)
        return data
