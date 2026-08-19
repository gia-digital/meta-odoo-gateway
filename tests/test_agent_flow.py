"""Flujos nuevos: burbujas, handoff por error, pestaña Agente."""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.agent_behavior import AgentBehavior
from app.services.agent_knowledge import TOOL_RULES


def _fast_behavior(**overrides) -> AgentBehavior:
    data = dict(
        debounce_seconds=0.0,
        reply_max_bubbles=4,
        reply_bubble_delay_ms=0,
        reply_min_seconds=0.0,
        reply_think_seconds=0.0,
        reply_chars_per_sec=100.0,
        reply_max_delay_seconds=0.0,
        sources={},
    )
    data.update(overrides)
    return AgentBehavior(**data)


def test_tool_rules_tell_llm_when_to_split():
    assert "MENSAJES WHATSAPP" in TOOL_RULES
    assert "---" in TOOL_RULES
    assert "NUNCA separes" in TOOL_RULES or "misma idea" in TOOL_RULES.lower()
    assert "send_catalog" in TOOL_RULES


@pytest.mark.asyncio
async def test_knowledge_agent_tab_requires_auth(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "false")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/dashboard/knowledge/agent", follow_redirects=False)
    assert r.status_code == 303
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_deliver_reply_sends_marked_bubbles(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()

    sent: list[str] = []

    class FakeCW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def send_message(self, cid, content, private=False):
            sent.append(content)
            return {"id": len(sent)}

        async def update_last_seen(self, cid):
            return None

    service = MagicMock()
    service.add_outbound_message = AsyncMock()
    mark_read = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.routers.chatwoot_webhook.get_agent_behavior",
        AsyncMock(return_value=_fast_behavior()),
    )
    monkeypatch.setattr("app.routers.chatwoot_webhook.ChatwootClient", FakeCW)
    monkeypatch.setattr("app.routers.chatwoot_webhook.has_newer_inbound", lambda _id: False)
    monkeypatch.setattr(
        "app.routers.chatwoot_webhook._signal_inbound_whatsapp",
        mark_read,
    )

    from app.routers.chatwoot_webhook import _deliver_reply

    await _deliver_reply(
        service,
        MagicMock(),
        42,
        "Buen día.\n---\n¿Qué calibre busca?",
        started_at=time.monotonic(),
        inbound_source_id="wamid.inbound123",
    )
    assert sent == ["Buen día.", "¿Qué calibre busca?"]
    assert service.add_outbound_message.await_count == 2
    mark_read.assert_awaited_once_with(42, "wamid.inbound123", typing=True)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_deliver_reply_skips_when_newer_inbound(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()

    class FakeCW:
        async def __aenter__(self):
            raise AssertionError("no debe abrir Chatwoot si hay inbound nuevo")

        async def __aexit__(self, *args):
            return None

    service = MagicMock()
    service.add_outbound_message = AsyncMock()
    monkeypatch.setattr(
        "app.routers.chatwoot_webhook.get_agent_behavior",
        AsyncMock(return_value=_fast_behavior()),
    )
    monkeypatch.setattr("app.routers.chatwoot_webhook.ChatwootClient", FakeCW)
    monkeypatch.setattr("app.routers.chatwoot_webhook.has_newer_inbound", lambda _id: True)

    from app.routers.chatwoot_webhook import _deliver_reply

    await _deliver_reply(service, MagicMock(), 7, "Hola", started_at=time.monotonic())
    service.add_outbound_message.assert_not_awaited()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_first_agent_error_stays_pending(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("CHATWOOT_DEBOUNCE_SECONDS", "0")
    monkeypatch.setenv("AGENT_ERROR_HANDOFF_THRESHOLD", "3")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core.agent_behavior import invalidate_agent_behavior
    from app.services.turn_guard import reset_for_tests

    invalidate_agent_behavior()
    reset_for_tests()

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "content": "Hola",
        "conversation": {"id": 88, "status": "pending"},
        "contact": {"name": "Ana", "phone_number": "5215512345678"},
    }

    handoffs: list[int] = []
    sent: list[str] = []

    class FakeCW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def send_message(self, cid, content, private=False):
            sent.append(content)
            return {"id": 1}

        async def handoff_to_human(self, cid, note=None):
            handoffs.append(cid)
            return {}

        async def set_status(self, cid, status):
            return {}

    conv = SimpleNamespace(
        id=1,
        status=SimpleNamespace(value="active"),
        user_name="Ana",
        user_phone="5215512345678",
        user_email=None,
        messages=[],
        handed_off_at=None,
        qualification_reason=None,
    )
    service = MagicMock()
    service.get_or_create = AsyncMock(return_value=conv)
    service.add_inbound_message = AsyncMock()
    service.process_after_message = AsyncMock()
    service.add_outbound_message = AsyncMock()
    service.mark_handed_off = AsyncMock()
    service.resume_bot = AsyncMock()

    class FakeSession:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr("app.routers.chatwoot_webhook.SessionLocal", FakeSession)
    monkeypatch.setattr(
        "app.routers.chatwoot_webhook.ConversationService", lambda db: service
    )
    monkeypatch.setattr("app.routers.chatwoot_webhook.ChatwootClient", FakeCW)
    fast = _fast_behavior()
    monkeypatch.setattr(
        "app.routers.chatwoot_webhook.get_agent_behavior",
        AsyncMock(return_value=fast),
    )
    monkeypatch.setattr(
        "app.core.agent_behavior.get_agent_behavior",
        AsyncMock(return_value=fast),
    )
    monkeypatch.setattr("app.routers.chatwoot_webhook.has_newer_inbound", lambda _id: False)

    async def boom(**kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr("app.services.gia_agent.run_gia_agent", boom)

    from app.routers.chatwoot_webhook import AGENT_RETRY_REPLY, _process_incoming_message

    await _process_incoming_message(payload)
    assert handoffs == []
    service.mark_handed_off.assert_not_awaited()
    assert sent == [AGENT_RETRY_REPLY]
    reset_for_tests()
    invalidate_agent_behavior()
    get_settings.cache_clear()


def _webhook_fakes(monkeypatch, *, conv, service, boom=True):
    handoffs: list[int] = []
    sent: list[str] = []
    statuses: list[str] = []

    class FakeCW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def send_message(self, cid, content, private=False):
            sent.append(content)
            return {"id": len(sent)}

        async def handoff_to_human(self, cid, note=None):
            handoffs.append(cid)
            return {}

        async def set_status(self, cid, status):
            statuses.append(status)
            return {}

        async def list_messages(self, cid):
            return []

    class FakeSession:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr("app.routers.chatwoot_webhook.SessionLocal", FakeSession)
    monkeypatch.setattr(
        "app.routers.chatwoot_webhook.ConversationService", lambda db: service
    )
    monkeypatch.setattr("app.routers.chatwoot_webhook.ChatwootClient", FakeCW)
    fast = _fast_behavior()
    monkeypatch.setattr(
        "app.routers.chatwoot_webhook.get_agent_behavior",
        AsyncMock(return_value=fast),
    )
    monkeypatch.setattr(
        "app.core.agent_behavior.get_agent_behavior",
        AsyncMock(return_value=fast),
    )
    monkeypatch.setattr("app.routers.chatwoot_webhook.has_newer_inbound", lambda _id: False)
    if boom:

        async def _boom(**kwargs):
            raise RuntimeError("llm down")

        monkeypatch.setattr("app.services.gia_agent.run_gia_agent", _boom)
    return sent, handoffs, statuses


@pytest.mark.asyncio
async def test_third_agent_error_handoffs(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("CHATWOOT_DEBOUNCE_SECONDS", "0")
    monkeypatch.setenv("AGENT_ERROR_HANDOFF_THRESHOLD", "3")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core.agent_behavior import invalidate_agent_behavior
    from app.services.turn_guard import reset_for_tests

    invalidate_agent_behavior()
    reset_for_tests()

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "content": "Hola",
        "conversation": {"id": 89, "status": "pending"},
        "contact": {"name": "Ana", "phone_number": "5215512345678"},
    }
    conv = SimpleNamespace(
        id=2,
        status=SimpleNamespace(value="active"),
        user_name="Ana",
        user_phone="5215512345678",
        user_email=None,
        messages=[],
        handed_off_at=None,
        qualification_reason=None,
    )
    service = MagicMock()
    service.get_or_create = AsyncMock(return_value=conv)
    service.add_inbound_message = AsyncMock()
    service.process_after_message = AsyncMock()
    service.add_outbound_message = AsyncMock()
    service.mark_handed_off = AsyncMock()
    service.resume_bot = AsyncMock()
    sent, handoffs, _ = _webhook_fakes(monkeypatch, conv=conv, service=service)

    from app.routers.chatwoot_webhook import (
        AGENT_HANDOFF_REPLY,
        AGENT_RETRY_REPLY,
        _process_incoming_message,
    )

    await _process_incoming_message(payload)
    await _process_incoming_message(payload)
    assert handoffs == []
    await _process_incoming_message(payload)
    assert handoffs == [89]
    service.mark_handed_off.assert_awaited()
    assert sent == [AGENT_RETRY_REPLY, AGENT_RETRY_REPLY, AGENT_HANDOFF_REPLY]
    assert "en breve" not in AGENT_HANDOFF_REPLY.lower()
    reset_for_tests()
    invalidate_agent_behavior()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_deliver_reply_skips_when_human_replied(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.services.turn_guard import record_human_reply, reset_for_tests

    reset_for_tests()
    record_human_reply(7)

    class FakeCW:
        async def __aenter__(self):
            raise AssertionError("no debe abrir Chatwoot si un humano ya contestó")

        async def __aexit__(self, *args):
            return None

    service = MagicMock()
    service.add_outbound_message = AsyncMock()
    monkeypatch.setattr(
        "app.routers.chatwoot_webhook.get_agent_behavior",
        AsyncMock(return_value=_fast_behavior()),
    )
    monkeypatch.setattr("app.routers.chatwoot_webhook.ChatwootClient", FakeCW)
    monkeypatch.setattr("app.routers.chatwoot_webhook.has_newer_inbound", lambda _id: False)

    from app.routers.chatwoot_webhook import _deliver_reply

    await _deliver_reply(service, MagicMock(), 7, "Hola", started_at=time.monotonic())
    service.add_outbound_message.assert_not_awaited()
    reset_for_tests()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_open_assigned_bot_still_answers(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("CHATWOOT_DEBOUNCE_SECONDS", "0")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core.agent_behavior import invalidate_agent_behavior
    from app.services.turn_guard import reset_for_tests

    invalidate_agent_behavior()
    reset_for_tests()

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "content": "¿Siguen ahí?",
        "conversation": {
            "id": 10,
            "status": "open",
            "meta": {"assignee": {"name": "Luis", "type": "user"}},
        },
        "contact": {"name": "Ana", "phone_number": "5215512345678"},
    }
    conv = SimpleNamespace(
        id=2,
        status=SimpleNamespace(value="handed_off"),
        user_name="Ana",
        user_phone="5215512345678",
        user_email=None,
        messages=[],
        handed_off_at=None,
        human_replied_at=None,
        qualification_reason=None,
    )
    service = MagicMock()
    service.get_or_create = AsyncMock(return_value=conv)
    service.add_inbound_message = AsyncMock()
    service.process_after_message = AsyncMock()
    service.add_outbound_message = AsyncMock()
    service.mark_handed_off = AsyncMock()
    service.resume_bot = AsyncMock()
    service.mark_human_replied = AsyncMock()
    service.clear_human_reply = AsyncMock()

    sent, handoffs, statuses = _webhook_fakes(
        monkeypatch, conv=conv, service=service, boom=False
    )
    monkeypatch.setattr(
        "app.services.gia_agent.run_gia_agent",
        AsyncMock(return_value="Sí, aquí sigo. ¿Qué material busca?"),
    )

    from app.routers.chatwoot_webhook import _process_incoming_message

    await _process_incoming_message(payload)
    assert handoffs == []
    assert statuses == []
    assert sent == ["Sí, aquí sigo. ¿Qué material busca?"]
    service.resume_bot.assert_not_awaited()
    reset_for_tests()
    invalidate_agent_behavior()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_open_unassigned_does_not_return_to_pending(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("CHATWOOT_DEBOUNCE_SECONDS", "0")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core.agent_behavior import invalidate_agent_behavior
    from app.services.turn_guard import reset_for_tests

    invalidate_agent_behavior()
    reset_for_tests()

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "content": "Hola de nuevo",
        "conversation": {"id": 11, "status": "open"},
        "contact": {"name": "Ana", "phone_number": "5215512345678"},
    }
    conv = SimpleNamespace(
        id=3,
        status=SimpleNamespace(value="handed_off"),
        user_name="Ana",
        user_phone="5215512345678",
        user_email=None,
        messages=[],
        handed_off_at=None,
        human_replied_at=None,
        qualification_reason=None,
    )
    service = MagicMock()
    service.get_or_create = AsyncMock(return_value=conv)
    service.add_inbound_message = AsyncMock()
    service.process_after_message = AsyncMock()
    service.add_outbound_message = AsyncMock()
    service.mark_handed_off = AsyncMock()
    service.resume_bot = AsyncMock()
    service.mark_human_replied = AsyncMock()
    service.clear_human_reply = AsyncMock()

    sent, _, statuses = _webhook_fakes(
        monkeypatch, conv=conv, service=service, boom=False
    )
    monkeypatch.setattr(
        "app.services.gia_agent.run_gia_agent",
        AsyncMock(return_value="Buen día. ¿En qué le ayudo?"),
    )

    from app.routers.chatwoot_webhook import _process_incoming_message

    await _process_incoming_message(payload)
    assert statuses == []
    assert sent == ["Buen día. ¿En qué le ayudo?"]
    service.resume_bot.assert_not_awaited()
    reset_for_tests()
    invalidate_agent_behavior()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_human_outgoing_mutes_and_pending_unmutes(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("CHATWOOT_DEBOUNCE_SECONDS", "0")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core.agent_behavior import invalidate_agent_behavior
    from app.services.turn_guard import human_has_replied, reset_for_tests

    invalidate_agent_behavior()
    reset_for_tests()

    conv = SimpleNamespace(
        id=5,
        status=SimpleNamespace(value="handed_off"),
        user_name="Ana",
        user_phone="5215512345678",
        user_email=None,
        messages=[],
        handed_off_at=None,
        human_replied_at=None,
        qualification_reason=None,
    )
    service = MagicMock()
    service.get_or_create = AsyncMock(return_value=conv)
    service.add_inbound_message = AsyncMock()
    service.process_after_message = AsyncMock()
    service.add_outbound_message = AsyncMock()
    service.mark_handed_off = AsyncMock()
    service.resume_bot = AsyncMock()

    async def mark_replied(c):
        c.human_replied_at = object()
        return c

    async def clear_replied(c):
        c.human_replied_at = None
        return c

    service.mark_human_replied = AsyncMock(side_effect=mark_replied)
    service.clear_human_reply = AsyncMock(side_effect=clear_replied)

    sent, _, _ = _webhook_fakes(monkeypatch, conv=conv, service=service, boom=False)
    monkeypatch.setattr(
        "app.services.gia_agent.run_gia_agent",
        AsyncMock(return_value="Bot no debería hablar"),
    )

    from app.routers.chatwoot_webhook import (
        _process_human_outgoing,
        _process_incoming_message,
    )

    await _process_human_outgoing(
        {
            "event": "message_created",
            "message_type": "outgoing",
            "private": False,
            "content": "Hola, soy Luis de GIA",
            "sender": {"type": "user", "name": "Luis"},
            "conversation": {"id": 12, "status": "open"},
            "contact": {"name": "Ana", "phone_number": "5215512345678"},
        }
    )
    assert human_has_replied(12) is True
    service.mark_human_replied.assert_awaited()

    await _process_incoming_message(
        {
            "event": "message_created",
            "message_type": "incoming",
            "content": "Gracias",
            "conversation": {"id": 12, "status": "open"},
            "contact": {"name": "Ana", "phone_number": "5215512345678"},
        }
    )
    assert sent == []

    await _process_incoming_message(
        {
            "event": "message_created",
            "message_type": "incoming",
            "content": "¿Siguen ahí?",
            "conversation": {"id": 12, "status": "pending"},
            "contact": {"name": "Ana", "phone_number": "5215512345678"},
        }
    )
    assert human_has_replied(12) is False
    service.clear_human_reply.assert_awaited()
    assert sent == ["Bot no debería hablar"]
    reset_for_tests()
    invalidate_agent_behavior()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_attachment_without_text_skips_agent(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("CHATWOOT_DEBOUNCE_SECONDS", "0")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core.agent_behavior import invalidate_agent_behavior
    from app.services.turn_guard import reset_for_tests

    invalidate_agent_behavior()
    reset_for_tests()

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "content": "",
        "attachments": [{"file_type": "image", "data_url": "https://x/a.jpg"}],
        "conversation": {"id": 90, "status": "pending"},
        "contact": {"name": "Ana", "phone_number": "5215512345678"},
    }
    conv = SimpleNamespace(
        id=4,
        status=SimpleNamespace(value="active"),
        user_name="Ana",
        user_phone="5215512345678",
        user_email=None,
        messages=[],
        handed_off_at=None,
        qualification_reason=None,
    )
    service = MagicMock()
    service.get_or_create = AsyncMock(return_value=conv)
    service.add_inbound_message = AsyncMock()
    service.process_after_message = AsyncMock()
    service.add_outbound_message = AsyncMock()
    service.mark_handed_off = AsyncMock()
    service.resume_bot = AsyncMock()

    async def must_not_run(**kwargs):
        raise AssertionError("el adjunto sin texto no debe llamar al LLM")

    sent, handoffs, _ = _webhook_fakes(monkeypatch, conv=conv, service=service, boom=False)
    monkeypatch.setattr("app.services.gia_agent.run_gia_agent", must_not_run)

    from app.routers.chatwoot_webhook import ATTACHMENT_REPLY, _process_incoming_message

    await _process_incoming_message(payload)
    assert handoffs == []
    assert sent == [ATTACHMENT_REPLY]
    reset_for_tests()
    invalidate_agent_behavior()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_resolved_conversation_skips_bot(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("CHATWOOT_DEBOUNCE_SECONDS", "0")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core.agent_behavior import invalidate_agent_behavior
    from app.services.turn_guard import reset_for_tests

    invalidate_agent_behavior()
    reset_for_tests()

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "content": "Hola",
        "conversation": {"id": 13, "status": "resolved"},
        "contact": {"name": "Ana", "phone_number": "5215512345678"},
    }
    conv = SimpleNamespace(
        id=6,
        status=SimpleNamespace(value="handed_off"),
        user_name="Ana",
        user_phone="5215512345678",
        user_email=None,
        messages=[],
        handed_off_at=None,
        human_replied_at=None,
        qualification_reason=None,
    )
    service = MagicMock()
    service.get_or_create = AsyncMock(return_value=conv)
    service.add_inbound_message = AsyncMock()
    service.process_after_message = AsyncMock()
    service.add_outbound_message = AsyncMock()
    service.mark_handed_off = AsyncMock()
    service.resume_bot = AsyncMock()
    service.mark_human_replied = AsyncMock()
    service.clear_human_reply = AsyncMock()

    sent, _, _ = _webhook_fakes(monkeypatch, conv=conv, service=service, boom=False)

    async def must_not_run(**kwargs):
        raise AssertionError("resolved no debe llamar al LLM")

    monkeypatch.setattr("app.services.gia_agent.run_gia_agent", must_not_run)

    from app.routers.chatwoot_webhook import _process_incoming_message

    await _process_incoming_message(payload)
    assert sent == []
    service.add_inbound_message.assert_not_awaited()
    reset_for_tests()
    invalidate_agent_behavior()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_open_history_human_reply_mutes_bot(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("CHATWOOT_DEBOUNCE_SECONDS", "0")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core.agent_behavior import invalidate_agent_behavior
    from app.services.turn_guard import human_has_replied, reset_for_tests

    invalidate_agent_behavior()
    reset_for_tests()

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "content": "¿Sigue mi cotización?",
        "conversation": {"id": 14, "status": "open"},
        "contact": {"name": "Ana", "phone_number": "5215512345678"},
    }
    conv = SimpleNamespace(
        id=7,
        status=SimpleNamespace(value="handed_off"),
        user_name="Ana",
        user_phone="5215512345678",
        user_email=None,
        messages=[],
        handed_off_at=None,
        human_replied_at=None,
        qualification_reason=None,
    )
    service = MagicMock()
    service.get_or_create = AsyncMock(return_value=conv)
    service.add_inbound_message = AsyncMock()
    service.process_after_message = AsyncMock()
    service.add_outbound_message = AsyncMock()
    service.mark_handed_off = AsyncMock()
    service.resume_bot = AsyncMock()

    async def mark_replied(c):
        c.human_replied_at = object()
        return c

    service.mark_human_replied = AsyncMock(side_effect=mark_replied)
    service.clear_human_reply = AsyncMock()

    sent, _, _ = _webhook_fakes(monkeypatch, conv=conv, service=service, boom=False)

    class HistoryCW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def send_message(self, cid, content, private=False):
            sent.append(content)
            return {"id": len(sent)}

        async def handoff_to_human(self, cid, note=None):
            return {}

        async def set_status(self, cid, status):
            return {}

        async def list_messages(self, cid):
            return [
                {
                    "message_type": 1,
                    "private": False,
                    "sender": {"type": "user", "name": "Luis"},
                    "content": "Hola, soy Luis de GIA",
                }
            ]

    monkeypatch.setattr("app.routers.chatwoot_webhook.ChatwootClient", HistoryCW)
    monkeypatch.setattr(
        "app.services.gia_agent.run_gia_agent",
        AsyncMock(return_value="el bot no debería hablar"),
    )

    from app.routers.chatwoot_webhook import _process_incoming_message

    await _process_incoming_message(payload)
    assert sent == []
    assert human_has_replied(14) is True
    service.mark_human_replied.assert_awaited()
    reset_for_tests()
    invalidate_agent_behavior()
    get_settings.cache_clear()
