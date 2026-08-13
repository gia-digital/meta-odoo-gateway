"""Tests del webhook Chatwoot Agent Bot (sin llamar LLM)."""
import hashlib
import hmac

import pytest

from app.routers.chatwoot_webhook import (
    _contact_identity,
    _conversation_id,
    _incoming_content,
    _is_incoming_event,
    _message_type_is_incoming,
    _verify_chatwoot_signature,
)
from app.services.agent_knowledge import _faq_question, _format_faqs
from app.services.gia_agent import _parse_model, history_to_input


def test_message_type_incoming_variants():
    assert _message_type_is_incoming(0) is True
    assert _message_type_is_incoming("incoming") is True
    assert _message_type_is_incoming("Incoming") is True
    assert _message_type_is_incoming(1) is False
    assert _message_type_is_incoming("outgoing") is False


def test_is_incoming_flat_and_nested():
    flat = {"message_type": "incoming", "content": "Hola"}
    assert _is_incoming_event(flat) is True
    assert _incoming_content(flat) == "Hola"

    nested = {
        "message": {"message_type": 0, "content": "Cotizar lámina"},
        "conversation": {"id": 9, "status": "pending"},
    }
    assert _is_incoming_event(nested) is True
    assert _incoming_content(nested) == "Cotizar lámina"

    outgoing = {"message": {"message_type": "outgoing", "content": "bot"}}
    assert _is_incoming_event(outgoing) is False


def test_conversation_id_and_contact():
    payload = {
        "conversation": {"id": 42, "display_id": 7, "status": "pending"},
        "contact": {
            "name": "Carlos",
            "phone_number": "+52 55 1234 5678",
            "email": "c@ex.com",
        },
        "content": "Hola",
        "message_type": "incoming",
    }
    assert _conversation_id(payload) == 42
    external, name, phone, email = _contact_identity(payload)
    assert external == "525512345678"
    assert name == "Carlos"
    assert email == "c@ex.com"
    assert phone is not None


def test_chatwoot_signature():
    secret = "whsec_test"
    body = b'{"event":"message_created"}'
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert _verify_chatwoot_signature(body, digest, secret) is True
    assert _verify_chatwoot_signature(body, f"sha256={digest}", secret) is True
    assert _verify_chatwoot_signature(body, "deadbeef", secret) is False

    # Formato actual Chatwoot: HMAC(timestamp + "." + body)
    ts = "1710000000"
    signed = f"{ts}.".encode() + body
    digest_ts = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    assert (
        _verify_chatwoot_signature(body, f"sha256={digest_ts}", secret, ts) is True
    )
    assert _verify_chatwoot_signature(body, f"sha256={digest_ts}", secret, None) is False


def test_history_to_input_dicts():
    text = history_to_input(
        [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "Buen día"},
        ]
    )
    assert "Cliente: Hola" in text
    assert "Asistente: Buen día" in text


def test_parse_model_routes_openai_to_responses():
    assert _parse_model("openai/gpt-5.6-luna") == (
        "openai_responses",
        "gpt-5.6-luna",
    )
    assert _parse_model("gpt-5.6-luna") == ("openai_responses", "gpt-5.6-luna")
    assert _parse_model("anthropic/claude-sonnet-4-20250514") == (
        "litellm",
        "anthropic/claude-sonnet-4-20250514",
    )


def test_faq_formatter_uses_singular_question():
    faqs = [
        {
            "question": "¿Manejan inoxidable o aluminio?",
            "answer": "No, únicamente acero al carbono.",
        }
    ]
    assert _faq_question(faqs[0]).startswith("¿Manejan inoxidable")
    text = _format_faqs(faqs, char_limit=5000)
    assert "P: ¿Manejan inoxidable o aluminio?" in text
    assert "(sin pregunta)" not in text


@pytest.mark.asyncio
async def test_webhook_disabled_returns_disabled(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "false")
    monkeypatch.setenv("META_VERIFY_TOKEN", "v")
    monkeypatch.setenv("META_APP_SECRET", "s")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()

    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/webhook/chatwoot",
            json={
                "event": "message_created",
                "content": "Hola",
                "message_type": "incoming",
                "conversation": {"id": 1, "status": "pending"},
            },
        )
    assert r.status_code == 200
    assert r.json()["status"] == "disabled"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_create_lead_chatwoot_source(monkeypatch):
    monkeypatch.setenv("ODOO_ENABLED", "false")
    monkeypatch.setenv("META_VERIFY_TOKEN", "v")
    monkeypatch.setenv("META_APP_SECRET", "s")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()

    from unittest.mock import AsyncMock, MagicMock

    from app.models.conversation import Channel, QualificationSource
    from app.services.conversation import ConversationService

    db = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    service = ConversationService(db)
    fake_conv = MagicMock()
    fake_conv.id = 99
    fake_conv.status.value = "qualified"
    fake_conv.messages = []
    fake_conv.product_interest = None
    fake_conv.lead_summary = None
    fake_conv.budget = None
    fake_conv.timeline = None
    fake_conv.preferred_contact_time = None
    fake_conv.user_name = None
    fake_conv.user_phone = None
    fake_conv.user_email = None
    fake_conv.qualified_at = None

    service.get_or_create = AsyncMock(return_value=fake_conv)

    result = await service.create_lead_from_payload(
        channel=Channel.whatsapp,
        external_user_id="5215511112222",
        reason="Cotización",
        summary="Lámina 10 ton",
        product_interest="Lámina",
        qualification_source=QualificationSource.chatwoot_agent,
    )
    assert result is fake_conv
    assert fake_conv.qualification_source == QualificationSource.chatwoot_agent
    get_settings.cache_clear()
