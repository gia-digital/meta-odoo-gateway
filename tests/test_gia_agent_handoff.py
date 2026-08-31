"""Escalado duplicado y fallback cuando el LLM no devuelve texto."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.conversation import Channel, ConversationStatus
from app.services.gia_agent import (
    BotContext,
    _conversation_handed_off,
    _empty_reply_fallback,
    _handoff_note_lead,
)


def test_handoff_note_lead_prefix():
    first = _handoff_note_lead(
        already_handed_off=False,
        team_label="recepción",
        reason="Cotización",
        summary="Tubería 2\"",
    )
    again = _handoff_note_lead(
        already_handed_off=True,
        team_label="recepción",
        reason="Pide asesor",
        summary="Reintento",
    )
    assert first.startswith("Lead creado y escalado")
    assert again.startswith("Re-escalado")


def test_conversation_handed_off_by_status():
    conv = SimpleNamespace(
        status=ConversationStatus.handed_off,
        handed_off_at=None,
    )
    assert _conversation_handed_off(conv) is True


def test_conversation_handed_off_by_timestamp():
    conv = SimpleNamespace(
        status=ConversationStatus.qualified,
        handed_off_at=datetime.now(timezone.utc),
    )
    assert _conversation_handed_off(conv) is True


def test_empty_reply_fallback_differs_when_handed_off():
    default = _empty_reply_fallback(handed_off=False)
    handed = _empty_reply_fallback(handed_off=True)
    assert default != handed
    assert "canalizarle" in default
    assert "ya quedó registrado" in handed


@pytest.mark.asyncio
async def test_run_gia_agent_uses_handed_off_fallback_when_output_empty(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()

    conv = SimpleNamespace(
        id=1,
        status=ConversationStatus.handed_off,
        handed_off_at=datetime.now(timezone.utc),
        messages=[],
    )
    ctx = BotContext(
        db=MagicMock(),
        conversation=conv,
        channel=Channel.whatsapp,
        external_user_id="5215511112222",
        chatwoot_conversation_id=1,
        handed_off=True,
    )

    class FakeResult:
        final_output = ""

    class FakeRunner:
        @staticmethod
        async def run(*args, **kwargs):
            return FakeResult()

    monkeypatch.setattr("app.services.gia_agent.build_agent_instructions", AsyncMock(return_value="inst"))
    monkeypatch.setattr("app.services.gia_agent.retrieve_knowledge", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.gia_agent.get_llm_runtime", AsyncMock())
    monkeypatch.setattr("app.services.gia_agent.build_gia_agent", lambda *a, **k: object())
    monkeypatch.setattr("agents.Runner", FakeRunner)

    from app.services.gia_agent import run_gia_agent

    reply = await run_gia_agent(ctx=ctx, user_message="Sí, por favor")
    assert "ya quedó registrado" in reply
    get_settings.cache_clear()
