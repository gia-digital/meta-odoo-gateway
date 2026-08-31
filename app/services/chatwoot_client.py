"""Cliente HTTP async para la API de Chatwoot (Agent Bot)."""
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class ChatwootError(Exception):
    pass


class ChatwootRetryableError(ChatwootError):
    """5xx / 429 / red: tiene sentido reintentar."""

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

    async def send_attachment(
        self,
        conversation_id: int,
        file_path: Path,
        *,
        content: str = "",
        filename: Optional[str] = None,
        mime: str = "application/pdf",
    ) -> Dict[str, Any]:
        """POST outgoing message with a file (WhatsApp document via Chatwoot).

        Cada envío vuelve a subir el archivo: Chatwoot no reutiliza el media_id
        de WhatsApp entre conversaciones. Un 4xx no se reintenta (evitar subir
        de nuevo un PDF grande si el request está mal).
        """
        path = Path(file_path)
        if not path.is_file():
            raise ChatwootError(f"attachment missing: {path}")
        name = filename or path.name
        file_bytes = path.read_bytes()
        return await self._post_attachment(
            conversation_id,
            file_bytes=file_bytes,
            filename=name,
            content=content,
            mime=mime,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
        retry=retry_if_exception_type((httpx.RequestError, ChatwootRetryableError)),
        reraise=True,
    )
    async def _post_attachment(
        self,
        conversation_id: int,
        *,
        file_bytes: bytes,
        filename: str,
        content: str,
        mime: str,
    ) -> Dict[str, Any]:
        assert self._client is not None
        url = self._account_path(f"/conversations/{conversation_id}/messages")
        data = {
            "content": content,
            "message_type": "outgoing",
            "private": "false",
        }
        r = await self._client.post(
            url,
            data=data,
            files={"attachments[]": (filename, file_bytes, mime)},
            timeout=120.0,
        )
        if r.status_code >= 400:
            logger.error(
                "chatwoot_send_attachment_failed",
                status=r.status_code,
                body=r.text[:500],
                conversation_id=conversation_id,
                filename=filename,
            )
            err_cls = (
                ChatwootRetryableError
                if r.status_code == 429 or r.status_code >= 500
                else ChatwootError
            )
            raise err_cls(f"send_attachment failed: {r.status_code} {r.text[:300]}")
        payload = r.json() if r.content else {}
        logger.info(
            "chatwoot_attachment_sent",
            conversation_id=conversation_id,
            message_id=payload.get("id"),
            filename=filename,
            bytes=len(file_bytes),
        )
        return payload

    async def update_last_seen(self, conversation_id: int) -> None:
        """Marca el hilo como visto en Chatwoot (unread interno; no WhatsApp)."""
        assert self._client is not None
        url = self._account_path(f"/conversations/{conversation_id}/update_last_seen")
        r = await self._client.post(url)
        if r.status_code >= 400:
            logger.warning(
                "chatwoot_update_last_seen_failed",
                status=r.status_code,
                body=r.text[:300],
                conversation_id=conversation_id,
            )
            raise ChatwootError(
                f"update_last_seen failed: {r.status_code} {r.text[:300]}"
            )
        logger.info("chatwoot_update_last_seen", conversation_id=conversation_id)

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

    async def list_messages(self, conversation_id: int) -> List[Dict[str, Any]]:
        """Últimos mensajes del hilo (red de seguridad si no llega outgoing al bot)."""
        assert self._client is not None
        url = self._account_path(f"/conversations/{conversation_id}/messages")
        r = await self._client.get(url)
        if r.status_code >= 400:
            raise ChatwootError(
                f"list_messages failed: {r.status_code} {r.text[:300]}"
            )
        data = r.json() if r.content else {}
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if not isinstance(data, dict):
            return []
        payload = data.get("payload")
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            nested = payload.get("payload") or payload.get("messages")
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        messages = data.get("messages")
        if isinstance(messages, list):
            return [item for item in messages if isinstance(item, dict)]
        return []

    async def assign_conversation(
        self,
        conversation_id: int,
        *,
        team_id: Optional[int] = None,
        assignee_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Asigna el hilo a un equipo y/o agente (API Conversation Assignments)."""
        assert self._client is not None
        if team_id is None and assignee_id is None:
            raise ChatwootError("assign_conversation requires team_id or assignee_id")
        url = self._account_path(f"/conversations/{conversation_id}/assignments")
        payload: Dict[str, Any] = {}
        if assignee_id is not None:
            payload["assignee_id"] = assignee_id
        elif team_id is not None:
            payload["team_id"] = team_id
        r = await self._client.post(url, json=payload)
        if r.status_code >= 400:
            logger.error(
                "chatwoot_assign_failed",
                status=r.status_code,
                body=r.text[:500],
                conversation_id=conversation_id,
                team_id=team_id,
                assignee_id=assignee_id,
            )
            raise ChatwootError(f"assign failed: {r.status_code} {r.text[:300]}")
        data = r.json() if r.content else {}
        logger.info(
            "chatwoot_assigned",
            conversation_id=conversation_id,
            team_id=team_id,
            assignee_id=assignee_id,
        )
        return data if isinstance(data, dict) else {}

    async def handoff_to_human(
        self,
        conversation_id: int,
        *,
        note: Optional[str] = None,
        team_id: Optional[int] = None,
        assignee_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Asigna equipo/agente y luego cambia status a open.

        El equipo va primero (aún en pending) para que la auto-asignación
        de Chatwoot (inbox + toggle del equipo) elija un miembro del
        equipo correcto al abrir el hilo, sin repartir antes entre todos
        los colaboradores del inbox.

        El bot sigue contestando hasta que un humano escriba en público;
        asignar equipo o mirar el hilo no lo calla.
        """
        if team_id is not None or assignee_id is not None:
            try:
                await self.assign_conversation(
                    conversation_id,
                    team_id=team_id,
                    assignee_id=assignee_id,
                )
            except Exception as exc:
                logger.error(
                    "chatwoot_handoff_assign_failed",
                    conversation_id=conversation_id,
                    team_id=team_id,
                    assignee_id=assignee_id,
                    error=str(exc),
                )
        data = await self.set_status(conversation_id, "open")
        logger.info(
            "chatwoot_handed_off",
            conversation_id=conversation_id,
            team_id=team_id,
            assignee_id=assignee_id,
        )
        if note:
            try:
                await self.send_message(conversation_id, note, private=True)
            except Exception as exc:
                logger.error(
                    "chatwoot_handoff_note_failed",
                    conversation_id=conversation_id,
                    error=str(exc),
                )
        return data


def resolve_handoff_queue(queue: str = "") -> tuple[int, str]:
    """
    Mapea el nombre semántico del agente a (team_id, etiqueta).
    Default: recepción. Los IDs viven en env (CHATWOOT_TEAM_*_ID).
    """
    settings = get_settings()
    q = (queue or "").strip().lower().replace("-", "_").replace(" ", "_")
    if q in (
        "important",
        "importante",
        "prospectos_importantes",
        "prospecto_importante",
        "vip",
        "hot",
    ):
        return settings.chatwoot_team_important_id, "prospectos importantes"
    return settings.chatwoot_team_reception_id, "recepción"
