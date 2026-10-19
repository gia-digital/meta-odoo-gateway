"""Cierre de ciclo al marcar resuelta y pedido nuevo después."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.conversation import Channel, ConversationStatus
from app.services.conversation import (
    ConversationService,
    cycle_private_note,
    decide_inbound_cycle,
)


def test_decide_inbound_cycle_windows():
    now = datetime(2026, 10, 19, 18, 0, tzinfo=timezone.utc)
    assert (
        decide_inbound_cycle(
            resolved_at=None, payload_status="pending", now=now, reopen_hours=24
        )
        == "continue"
    )
    assert (
        decide_inbound_cycle(
            resolved_at=None, payload_status="resolved", now=now, reopen_hours=24
        )
        == "new"
    )
    assert (
        decide_inbound_cycle(
            resolved_at=now - timedelta(hours=2),
            payload_status="pending",
            now=now,
            reopen_hours=24,
        )
        == "reopen"
    )
    assert (
        decide_inbound_cycle(
            resolved_at=now - timedelta(hours=2),
            payload_status="resolved",
            now=now,
            reopen_hours=24,
        )
        == "reopen"
    )
    assert (
        decide_inbound_cycle(
            resolved_at=now - timedelta(hours=24),
            payload_status="pending",
            now=now,
            reopen_hours=24,
        )
        == "new"
    )
    assert (
        decide_inbound_cycle(
            resolved_at=now - timedelta(days=90),
            payload_status="pending",
            now=now,
            reopen_hours=24,
        )
        == "new"
    )


def test_cycle_private_note_uses_display_timezone(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("DISPLAY_TIMEZONE", "America/Mexico_City")
    from app.core.config import get_settings

    get_settings.cache_clear()
    note = cycle_private_note(datetime(2026, 3, 15, 20, 30, tzinfo=timezone.utc))
    assert "15/03/2026 14:30" in note
    assert "pedido nuevo" in note
    get_settings.cache_clear()


def _service() -> tuple[ConversationService, MagicMock]:
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    return ConversationService(db), db


@pytest.mark.asyncio
async def test_mark_cycle_resolved_keeps_lead():
    service, db = _service()
    conv = SimpleNamespace(
        id=3,
        resolved_at=None,
        chatwoot_conversation_id=None,
        status=ConversationStatus.handed_off,
        product_interest="varilla",
        lead_summary="10 ton",
    )

    async def latest(*_args, **kwargs):
        assert kwargs["include_resolved"] is False
        return conv

    service._latest_cycle = latest  # type: ignore[method-assign]
    result = await service.mark_cycle_resolved(
        channel=Channel.whatsapp,
        external_user_id="5215512345678",
        chatwoot_conversation_id=13,
    )
    assert result is conv
    assert conv.resolved_at is not None
    assert conv.chatwoot_conversation_id == 13
    assert conv.status == ConversationStatus.handed_off
    assert conv.product_interest == "varilla"
    assert conv.lead_summary == "10 ton"
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_mark_cycle_resolved_is_idempotent_when_already_closed():
    service, db = _service()

    async def latest(*_args, **_kwargs):
        return None

    service._latest_cycle = latest  # type: ignore[method-assign]
    result = await service.mark_cycle_resolved(
        channel=Channel.whatsapp,
        external_user_id="5215512345678",
        chatwoot_conversation_id=13,
    )
    assert result is None
    db.commit.assert_not_awaited()


def _old_cycle(**overrides):
    data = dict(
        id=1,
        resolved_at=None,
        status=ConversationStatus.handed_off,
        user_name="Ana",
        user_phone="5215512345678",
        user_email="ana@example.com",
        product_interest="varilla",
        lead_summary="10 ton",
        chatwoot_conversation_id=9,
        messages=[object()],
        fresh_cycle=False,
        previous_resolved_at=None,
    )
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.mark.asyncio
async def test_inbound_after_window_starts_empty_cycle(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    service, _db = _service()
    old = _old_cycle(
        resolved_at=datetime.now(timezone.utc) - timedelta(days=40)
    )
    created: dict = {}

    async def latest(*_args, **_kwargs):
        return old

    async def create(**kwargs):
        created.update(kwargs)
        return SimpleNamespace(
            id=2,
            messages=[],
            status=ConversationStatus.active,
            resolved_at=None,
            product_interest=None,
            lead_summary=None,
            handed_off_at=None,
            human_replied_at=None,
        )

    service._latest_cycle = latest  # type: ignore[method-assign]
    service._create_conversation = create  # type: ignore[method-assign]
    conv = await service.get_or_create(
        Channel.whatsapp,
        "5215512345678",
        apply_cycle=True,
        payload_status="pending",
        chatwoot_conversation_id=9,
    )
    assert conv.id == 2
    assert conv.fresh_cycle is True
    assert conv.previous_resolved_at == old.resolved_at
    assert conv.product_interest is None
    assert old.product_interest == "varilla"
    assert old.lead_summary == "10 ton"
    assert old.messages
    assert created["user_name"] == "Ana"
    assert created["user_phone"] == "5215512345678"
    assert created["user_email"] == "ana@example.com"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_inbound_within_window_reopens_same_cycle(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    service, db = _service()
    old = _old_cycle(resolved_at=datetime.now(timezone.utc) - timedelta(hours=2))

    async def latest(*_args, **_kwargs):
        return old

    async def create(**_kwargs):
        raise AssertionError("dentro de 24 h no se crea fila nueva")

    service._latest_cycle = latest  # type: ignore[method-assign]
    service._create_conversation = create  # type: ignore[method-assign]
    conv = await service.get_or_create(
        Channel.whatsapp,
        "5215512345678",
        apply_cycle=True,
        payload_status="pending",
        chatwoot_conversation_id=9,
    )
    assert conv is old
    assert old.resolved_at is None
    assert old.fresh_cycle is False
    assert old.product_interest == "varilla"
    db.commit.assert_awaited()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_resolved_payload_without_timestamp_starts_new_cycle(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    service, db = _service()
    old = _old_cycle(resolved_at=None)
    created: dict = {}

    async def latest(*_args, **_kwargs):
        return old

    async def create(**kwargs):
        created.update(kwargs)
        return SimpleNamespace(id=4, messages=[], product_interest=None)

    service._latest_cycle = latest  # type: ignore[method-assign]
    service._create_conversation = create  # type: ignore[method-assign]
    conv = await service.get_or_create(
        Channel.whatsapp,
        "5215512345678",
        apply_cycle=True,
        payload_status="resolved",
        chatwoot_conversation_id=9,
    )
    assert old.resolved_at is not None
    assert old.status == ConversationStatus.handed_off
    assert conv.fresh_cycle is True
    assert conv.id == 4
    assert created["user_name"] == "Ana"
    db.commit.assert_awaited()
    get_settings.cache_clear()


def test_should_close_cycle_only_on_resolved():
    from app.routers.chatwoot_webhook import should_close_cycle

    resolved = {
        "id": 13,
        "status": "resolved",
        "channel": "Channel::Whatsapp",
        "meta": {"sender": {"phone_number": "+5215512345678", "name": "Ana"}},
    }
    assert should_close_cycle("conversation_resolved", resolved) is True
    assert should_close_cycle("conversation_status_changed", resolved) is True
    opened = {
        **resolved,
        "status": "open",
        "changed_attributes": [
            {"status": {"previous_value": "pending", "current_value": "open"}}
        ],
    }
    assert should_close_cycle("conversation_status_changed", opened) is False
    assert should_close_cycle("conversation_updated", resolved) is False
    pending_change = {
        "status": "pending",
        "changed_attributes": [
            {"status": {"previous_value": "resolved", "current_value": "pending"}}
        ],
    }
    assert should_close_cycle("conversation_status_changed", pending_change) is False


@pytest.mark.asyncio
async def test_process_cycle_resolved_marks_contact(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings
    from app.services.turn_guard import human_has_replied, record_human_reply, reset_for_tests

    get_settings.cache_clear()
    reset_for_tests()
    record_human_reply(13)

    service = MagicMock()
    service.mark_cycle_resolved = AsyncMock()

    class FakeSession:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr("app.routers.chatwoot_webhook.SessionLocal", FakeSession)
    monkeypatch.setattr(
        "app.routers.chatwoot_webhook.ConversationService", lambda db: service
    )

    from app.routers.chatwoot_webhook import _process_cycle_resolved

    await _process_cycle_resolved(
        {
            "event": "conversation_resolved",
            "id": 13,
            "status": "resolved",
            "channel": "Channel::Whatsapp",
            "meta": {"sender": {"name": "Ana", "phone_number": "+5215512345678"}},
        }
    )
    service.mark_cycle_resolved.assert_awaited()
    kwargs = service.mark_cycle_resolved.await_args.kwargs
    assert kwargs["external_user_id"] == "5215512345678"
    assert kwargs["chatwoot_conversation_id"] == 13
    assert kwargs["channel"] == Channel.whatsapp
    assert human_has_replied(13) is False
    reset_for_tests()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_webhook_queues_resolved_and_ignores_assignment(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET", "")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    queued: list = []

    async def fake_process(payload):
        queued.append(payload.get("event"))

    monkeypatch.setattr(
        "app.routers.chatwoot_webhook._process_cycle_resolved", fake_process
    )

    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resolved = await client.post(
            "/webhook/chatwoot",
            json={
                "event": "conversation_resolved",
                "id": 13,
                "status": "resolved",
                "meta": {"sender": {"phone_number": "+5215512345678"}},
            },
        )
        assigned = await client.post(
            "/webhook/chatwoot",
            json={
                "event": "conversation_updated",
                "id": 13,
                "status": "open",
                "changed_attributes": [
                    {
                        "assignee_id": {
                            "previous_value": None,
                            "current_value": 4,
                        }
                    }
                ],
            },
        )
    assert resolved.status_code == 200
    assert resolved.json()["kind"] == "conversation_resolved"
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "ignored"
    assert queued == ["conversation_resolved"]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_fresh_cycle_note_and_prompt_flag(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("CHATWOOT_DEBOUNCE_SECONDS", "0")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.agent_behavior import invalidate_agent_behavior
    from app.core.config import get_settings
    from app.services.turn_guard import reset_for_tests

    get_settings.cache_clear()
    invalidate_agent_behavior()
    reset_for_tests()

    from tests.test_agent_flow import _fast_behavior, _webhook_fakes

    closed = datetime(2026, 1, 2, 18, 0, tzinfo=timezone.utc)
    conv = SimpleNamespace(
        id=6,
        status=ConversationStatus.active,
        user_name="Ana",
        user_phone="5215512345678",
        user_email=None,
        messages=[],
        handed_off_at=None,
        human_replied_at=None,
        qualification_reason=None,
        fresh_cycle=True,
        previous_resolved_at=closed,
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
    monkeypatch.setattr(
        "app.routers.chatwoot_webhook.get_agent_behavior",
        AsyncMock(return_value=_fast_behavior()),
    )
    seen: dict = {}

    async def fake_agent(*, ctx, user_message, history_messages):
        seen["fresh_cycle"] = ctx.fresh_cycle
        seen["history"] = list(history_messages)
        return "¿Qué material busca?"

    monkeypatch.setattr("app.services.gia_agent.run_gia_agent", fake_agent)

    from app.routers.chatwoot_webhook import _process_incoming_message

    await _process_incoming_message(
        {
            "event": "message_created",
            "message_type": "incoming",
            "content": "Quiero lamina",
            "conversation": {"id": 13, "status": "pending"},
            "contact": {"name": "Ana", "phone_number": "5215512345678"},
        }
    )
    assert seen["fresh_cycle"] is True
    assert seen["history"] == []
    assert any("pedido nuevo" in item for item in sent)
    assert sent[-1] == "¿Qué material busca?"
    reset_for_tests()
    invalidate_agent_behavior()
    get_settings.cache_clear()
