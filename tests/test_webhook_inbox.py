"""Bandeja durable: dedupe, claim y replay sin doble respuesta."""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from app.services.chatwoot_payload import bot_replied_after, message_to_webhook_payload
from app.services.webhook_inbox import dedupe_key


def test_dedupe_key_message_and_resolved():
    assert dedupe_key("message", {"id": 42, "content": "hola"}) == "msg:42"
    assert (
        dedupe_key("resolved", {"id": 9, "event": "conversation_resolved"})
        == "evt:conversation_resolved:9"
    )
    nested = dedupe_key(
        "resolved",
        {"conversation": {"id": 3}, "event": "conversation_status_changed"},
    )
    assert nested == "evt:conversation_resolved:3"


def test_bot_replied_after_uses_later_outgoing():
    messages = [
        {
            "id": 50,
            "message_type": 0,
            "content": "Hola",
            "created_at": 100,
            "sender": {"type": "contact"},
        },
        {
            "id": 51,
            "message_type": 1,
            "content": "ya respondí",
            "created_at": 200,
            "private": False,
            "sender": {"type": "agent_bot"},
        },
    ]
    assert bot_replied_after(messages, "50") is True
    assert bot_replied_after(messages, "51") is False


def test_bot_replied_after_ignores_earlier_bot_message():
    messages = [
        {
            "id": 10,
            "message_type": 1,
            "content": "antes",
            "created_at": 50,
            "private": False,
            "sender": {"type": "agent_bot"},
        },
        {
            "id": 11,
            "message_type": 0,
            "content": "nuevo",
            "created_at": 80,
            "sender": {"type": "contact"},
        },
    ]
    assert bot_replied_after(messages, "11") is False


def test_message_to_webhook_payload_keeps_ids():
    payload = message_to_webhook_payload(
        {
            "id": 7,
            "status": "open",
            "meta": {
                "channel": "Channel::Whatsapp",
                "sender": {"phone_number": "+5215512345678", "name": "Ana"},
            },
        },
        {
            "id": 99,
            "content": "cotización",
            "message_type": 0,
            "created_at": 1_700_000_000,
            "sender": {"type": "contact", "name": "Ana"},
            "source_id": "wamid.abc",
        },
    )
    assert payload["event"] == "message_created"
    assert payload["id"] == 99
    assert payload["conversation"]["id"] == 7
    assert payload["conversation"]["status"] == "open"
    assert payload["inbox"]["channel_type"] == "Channel::Whatsapp"
    assert dedupe_key("message", payload) == "msg:99"


@pytest_asyncio.fixture
async def inbox_db():
    """Cada test asyncio usa su propio loop; el pool global no puede cruzarlos."""
    from app.models.db import engine, init_db

    await engine.dispose()
    await init_db()
    yield
    await engine.dispose()


def _sample_payload(mid: str) -> dict:
    return {
        "event": "message_created",
        "id": mid,
        "content": "hola inbox",
        "message_type": "incoming",
        "conversation": {"id": 424242, "status": "pending"},
        "contact": {"phone_number": "+5215500000000"},
    }


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_and_claim_is_single(inbox_db):
    from app.services.webhook_inbox import claim, enqueue_webhook, load_row

    mid = f"test-{uuid.uuid4().hex}"
    payload = _sample_payload(mid)
    try:
        first = await enqueue_webhook(payload, kind="message", conversation_id=424242)
        second = await enqueue_webhook(payload, kind="message", conversation_id=424242)
        assert first is not None
        assert second is None
        won = await asyncio.gather(claim(first), claim(first))
        assert sum(1 for ok in won if ok) == 1
        row = await load_row(first)
        assert row is not None
        assert row.status == "processing"
    finally:
        await _delete_keys(f"msg:{mid}")


@pytest.mark.asyncio
async def test_retry_fails_after_five_attempts(inbox_db):
    from app.services.webhook_inbox import enqueue_webhook, load_row, mark_retry_many

    mid = f"test-{uuid.uuid4().hex}"
    try:
        row_id = await enqueue_webhook(
            _sample_payload(mid), kind="message", conversation_id=424242
        )
        assert row_id is not None
        for _ in range(5):
            await mark_retry_many([row_id], "chatwoot down")
        row = await load_row(row_id)
        assert row is not None
        assert row.attempts == 5
        assert row.status == "failed"
    finally:
        await _delete_keys(f"msg:{mid}")


@pytest.mark.asyncio
async def test_webhook_commits_pending_row_before_processing(monkeypatch, inbox_db):
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET", "")
    monkeypatch.setenv("ADMIN_API_TOKEN", "ci-admin-token")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.models.conversation import WebhookInbox
    from app.models.db import SessionLocal

    mid = f"test-{uuid.uuid4().hex}"
    seen: dict = {}

    async def spy(row_id: int) -> None:
        async with SessionLocal() as db:
            row = await db.get(WebhookInbox, row_id)
            seen["status"] = row.status if row else None
            seen["calls"] = seen.get("calls", 0) + 1

    monkeypatch.setattr("app.routers.chatwoot_webhook.process_inbox_row", spy)

    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    body = _sample_payload(mid)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/webhook/chatwoot", json=body)
            second = await client.post("/webhook/chatwoot", json=body)
        assert first.status_code == 200
        assert first.json()["queued"] == "true"
        assert second.status_code == 200
        assert seen["status"] == "pending"
        assert seen["calls"] == 1
    finally:
        await _delete_keys(f"msg:{mid}")
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_replay_does_not_call_the_agent(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("CHATWOOT_DEBOUNCE_SECONDS", "0")
    monkeypatch.setenv("ADMIN_API_TOKEN", "ci-admin-token")
    from app.core.agent_behavior import AgentBehavior, invalidate_agent_behavior
    from app.core.config import get_settings
    from app.services.turn_guard import reset_for_tests

    get_settings.cache_clear()
    invalidate_agent_behavior()
    reset_for_tests()

    class FakeCW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def list_messages(self, cid):
            return [
                {
                    "id": 50,
                    "message_type": 0,
                    "content": "Hola",
                    "created_at": 100,
                    "sender": {"type": "contact"},
                },
                {
                    "id": 51,
                    "message_type": 1,
                    "content": "respuesta",
                    "created_at": 200,
                    "private": False,
                    "sender": {"type": "agent_bot"},
                },
            ]

        async def send_message(self, *args, **kwargs):
            raise AssertionError("no debe reenviar")

    class FakeSession:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *args):
            return None

    conv = SimpleNamespace(
        id=1,
        status=SimpleNamespace(value="active"),
        user_name="Ana",
        user_phone="5215512345678",
        user_email=None,
        messages=[],
        handed_off_at=None,
        human_replied_at=None,
        fresh_cycle=False,
    )
    service = MagicMock()
    service.get_or_create = AsyncMock(return_value=conv)
    service.add_inbound_message = AsyncMock()
    service.process_after_message = AsyncMock()
    service.clear_human_reply = AsyncMock()

    fast = AgentBehavior(
        debounce_seconds=0.0,
        reply_max_bubbles=4,
        reply_bubble_delay_ms=0,
        reply_min_seconds=0.0,
        reply_think_seconds=0.0,
        reply_chars_per_sec=100.0,
        reply_max_delay_seconds=0.0,
        sources={},
    )
    monkeypatch.setattr("app.routers.chatwoot_webhook.SessionLocal", FakeSession)
    monkeypatch.setattr(
        "app.routers.chatwoot_webhook.ConversationService", lambda db: service
    )
    monkeypatch.setattr("app.routers.chatwoot_webhook.ChatwootClient", FakeCW)
    monkeypatch.setattr(
        "app.routers.chatwoot_webhook.get_agent_behavior",
        AsyncMock(return_value=fast),
    )
    monkeypatch.setattr(
        "app.core.agent_behavior.get_agent_behavior",
        AsyncMock(return_value=fast),
    )

    async def boom(**kwargs):
        raise AssertionError("el agente no debe correr")

    monkeypatch.setattr("app.services.gia_agent.run_gia_agent", boom)

    from app.routers.chatwoot_webhook import _process_incoming_message

    result = await _process_incoming_message(
        {
            "event": "message_created",
            "id": 50,
            "message_type": "incoming",
            "content": "Hola",
            "conversation": {"id": 7, "status": "pending"},
            "contact": {"name": "Ana", "phone_number": "5215512345678"},
            "_inbox_id": 1,
            "_inbox_attempts": 1,
        }
    )
    assert result == [1]
    service.add_inbound_message.assert_awaited()
    reset_for_tests()
    invalidate_agent_behavior()
    get_settings.cache_clear()


async def _delete_keys(*keys: str) -> None:
    from sqlalchemy import delete

    from app.models.conversation import WebhookInbox
    from app.models.db import SessionLocal

    async with SessionLocal() as db:
        await db.execute(delete(WebhookInbox).where(WebhookInbox.dedupe_key.in_(keys)))
        await db.commit()
