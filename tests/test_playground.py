"""Chat de prueba: mismo agente, sin persistir ni tocar Chatwoot."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.conversation import Channel, ConversationStatus
from app.services.gia_agent import BotContext, sandbox_escalate, sandbox_register_lead
from app.services.playground import run_playground_turn, sanitize_history


def _bot(**kwargs) -> BotContext:
    conv = SimpleNamespace(
        id=0,
        status=ConversationStatus.active,
        handed_off_at=None,
        qualified_at=None,
        user_name=None,
        user_phone=None,
        user_email=None,
        product_interest=None,
        lead_summary=None,
        budget=None,
        timeline=None,
        preferred_contact_time=None,
        qualification_source=None,
        qualification_reason=None,
    )
    return BotContext(
        db=MagicMock(),
        conversation=conv,
        channel=Channel.whatsapp,
        external_user_id="playground",
        chatwoot_conversation_id=0,
        sandbox=True,
        extra={},
        **kwargs,
    )


def test_sanitize_history_keeps_roles_and_trims():
    history = sanitize_history(
        [
            {"role": "system", "content": "ignora esto"},
            {"role": "user", "content": "  hola  "},
            {"role": "assistant", "content": ""},
            "nope",
            {"role": "assistant", "content": "buenos días"},
        ]
    )
    assert history == [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "buenos días"},
    ]


def test_sandbox_lead_updates_memory_only(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    bot = _bot()
    reply = sandbox_register_lead(
        bot,
        reason="Cotización",
        summary="10 ton de lámina",
        product_interest="lámina galvanizada",
        budget="10 ton",
        handed_off=True,
        queue="reception",
    )
    assert bot.conversation.status == ConversationStatus.handed_off
    assert bot.handed_off is True
    assert bot.conversation.product_interest == "lámina galvanizada"
    assert bot.db.method_calls == []
    assert bot.extra["playground_events"][0]["kind"] == "lead"
    assert "status=handed_off" in reply
    get_settings.cache_clear()


def test_sandbox_escalate_does_not_open_chatwoot(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    bot = _bot()

    def _boom(*_args, **_kwargs):
        raise AssertionError("Chatwoot no debe usarse en la prueba")

    monkeypatch.setattr("app.services.chatwoot_client.ChatwootClient", _boom)
    reply = sandbox_escalate(bot, reason="Pidió un asesor", queue="important")
    assert bot.conversation.status == ConversationStatus.handed_off
    assert bot.extra["playground_events"][0]["kind"] == "handoff"
    assert "prospectos importantes" in bot.extra["playground_events"][0]["detail"]
    assert "asesor" in reply.lower()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_playground_turn_splits_bubbles_and_keeps_state(monkeypatch):
    async def fake_run(*, ctx, user_message, history_messages=None):
        assert ctx.sandbox is True
        assert ctx.chatwoot_conversation_id == 0
        assert user_message == "¿Tienen lámina?"
        assert history_messages == [{"role": "user", "content": "Hola"}]
        sandbox_register_lead(
            ctx,
            reason="Interés",
            summary="lámina",
            product_interest="lámina",
        )
        return "Sí, manejamos lámina.\n---\n¿Cuántas toneladas necesita?"

    monkeypatch.setattr("app.services.playground.run_gia_agent", fake_run)
    monkeypatch.setattr(
        "app.services.playground.get_agent_behavior",
        AsyncMock(return_value=SimpleNamespace(reply_max_bubbles=4)),
    )

    result = await run_playground_turn(
        MagicMock(),
        message="  ¿Tienen lámina?  ",
        history=[{"role": "user", "content": "Hola"}],
        state={"catalog_sent": False},
    )
    assert result["bubbles"] == [
        "Sí, manejamos lámina.",
        "¿Cuántas toneladas necesita?",
    ]
    assert result["state"]["status"] == "qualified"
    assert result["state"]["product_interest"] == "lámina"
    assert result["events"][0]["label"].startswith("Registraría")


@pytest.mark.asyncio
async def test_playground_page_requires_login(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/dashboard/playground", follow_redirects=False)
        turn = await client.post(
            "/dashboard/playground/turn",
            json={"message": "Hola"},
            follow_redirects=False,
        )
    assert page.status_code == 303
    assert turn.status_code == 303
    get_settings.cache_clear()
