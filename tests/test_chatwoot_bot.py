"""Tests del webhook Chatwoot Agent Bot (sin llamar LLM)."""
import asyncio
import hashlib
import hmac
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.models.db import is_deadlock
from app.routers.chatwoot_webhook import (
    _contact_identity,
    _conversation_id,
    _incoming_content,
    _is_incoming_event,
    _merge_incoming_texts,
    _message_type_is_incoming,
    _resolve_channel,
    _verify_chatwoot_signature,
)
from app.models.conversation import Channel
from app.services.chatwoot_payload import (
    has_attachments,
    human_assignee_name,
    incoming_message_source_id,
    is_human_public_outgoing,
    latest_inbound_wamid_from_db_messages,
    latest_incoming_source_id,
    resolve_inbound_wamid_for_human_reply,
)
from app.services.turn_guard import last_inbound_wamid, record_inbound_wamid, reset_for_tests
from app.services.turn_guard import (
    debounce_payloads,
    is_agent_error_reason,
    record_agent_failure,
    record_agent_success,
    reset_for_tests,
)
from app.services.agent_knowledge import _faq_question, _format_faqs
from app.services.gia_agent import _parse_model, history_to_input
from app.services.reply_bubbles import (
    first_send_wait_seconds,
    next_bubble_wait_seconds,
    split_reply_bubbles,
)


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


def test_instagram_contact_identity_and_channel():
    ig_user = "17841470088715728"
    ig_mid = (
        "aWdfZAG1faXRlbToxOklHTWVzc2FnZAUlEOjE3ODQxNDcwMDg4NzE1NzI4OjM0MDI4MjM2"
        "Njg0MTcxMDMwMTI0NDI1OTc5MzEyMTQ3MDEwMjExNjozMjk2OTIzMTM0Njk1NjQ4OTk1"
        "MTc5NzU4NjUxODA4MTUzNgZDZD"
    )
    payload = {
        "conversation": {
            "id": 99,
            "status": "pending",
            "meta": {
                "channel": "Channel::Instagram",
                "sender": {"name": "Iñaki Guerrero", "identifier": ig_user},
            },
        },
        "inbox": {"channel_type": "Channel::Instagram", "name": "IG GIA"},
        "contact": {"name": "Iñaki Guerrero", "identifier": ig_user},
        "message": {"message_type": 0, "content": "Hola", "source_id": ig_mid},
        "content": "Hola",
        "message_type": "incoming",
        "source_id": ig_mid,
    }
    external, name, phone, _ = _contact_identity(payload)
    assert external == ig_user
    assert name == "Iñaki Guerrero"
    assert phone is None
    assert _resolve_channel(payload) == Channel.instagram


def test_instagram_falls_back_to_long_mid_when_no_contact_id():
    ig_mid = (
        "aWdfZAG1faXRlbToxOklHTWVzc2FnZAUlEOjE3ODQxNDcwMDg4NzE1NzI4OjM0MDI4MjM2"
        "Njg0MTcxMDMwMTI0NDI1OTc5MzEyMTQ3MDEwMjExNjozMjk2OTIzMTM0Njk1NjQ4OTk1"
        "MTc5NzU4NjUxODA4MTUzNgZDZD"
    )
    payload = {
        "inbox": {"channel_type": "Channel::Instagram"},
        "contact": {"name": "Anon"},
        "source_id": ig_mid,
    }
    external, _, phone, _ = _contact_identity(payload)
    assert external == ig_mid
    assert len(external) > 128
    assert phone is None
    assert _resolve_channel(payload) == Channel.instagram


def test_resolve_channel_whatsapp_inbox():
    payload = {
        "inbox": {"channel_type": "Channel::Whatsapp"},
        "contact": {"phone_number": "+525512345678"},
    }
    assert _resolve_channel(payload) == Channel.whatsapp


def test_incoming_message_source_id():
    nested = {
        "message": {
            "message_type": 0,
            "content": "Hola",
            "source_id": "wamid.ABC123",
        }
    }
    assert incoming_message_source_id(nested) == "wamid.ABC123"
    assert latest_incoming_source_id([{"content": "x"}, nested]) == "wamid.ABC123"


def test_resolve_inbound_wamid_for_human_reply():
    reset_for_tests()
    record_inbound_wamid(12, "wamid.cached")
    assert (
        resolve_inbound_wamid_for_human_reply(12, {}, db_messages=[])
        == "wamid.cached"
    )

    reset_for_tests()
    msg = SimpleNamespace(
        direction=SimpleNamespace(value="inbound"),
        raw_payload={
            "message_type": "incoming",
            "source_id": "wamid.fromdb",
        },
    )
    assert (
        resolve_inbound_wamid_for_human_reply(
            99,
            {},
            db_messages=[msg],
        )
        == "wamid.fromdb"
    )
    assert latest_inbound_wamid_from_db_messages([msg]) == "wamid.fromdb"
    reset_for_tests()


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


def test_human_assignee_and_attachments():
    assert human_assignee_name({"conversation": {"status": "open"}}) is None
    assert (
        human_assignee_name(
            {"meta": {"assignee": {"type": "agent_bot", "name": "GIA"}}}
        )
        is None
    )
    assert (
        human_assignee_name(
            {
                "conversation": {
                    "meta": {"assignee": {"type": "user", "name": "Ana"}}
                }
            }
        )
        == "Ana"
    )
    assert has_attachments({"message": {"attachments": [{"id": 1}]}}) is True
    assert has_attachments({"content": "hola"}) is False


def test_merge_incoming_and_agent_error_reason():
    batch = [
        {"message_type": "incoming", "content": "Hola"},
        {"message_type": "incoming", "content": "Hola"},
        {"message_type": "incoming", "content": "¿tienen lámina?"},
    ]
    assert _merge_incoming_texts(batch) == "Hola\n¿tienen lámina?"
    assert is_agent_error_reason("agent_error: timeout") is True
    assert is_agent_error_reason("Qualified by Chatwoot Agent Bot") is False


def test_human_public_outgoing_detection():
    assert (
        is_human_public_outgoing(
            {
                "message_type": "outgoing",
                "private": False,
                "sender": {"type": "user", "name": "Luis"},
                "content": "Hola, soy Luis",
            }
        )
        is True
    )
    assert (
        is_human_public_outgoing(
            {
                "message": {
                    "message_type": 1,
                    "private": True,
                    "sender": {"type": "user", "name": "Luis"},
                    "content": "nota interna",
                }
            }
        )
        is False
    )
    assert (
        is_human_public_outgoing(
            {
                "message_type": "outgoing",
                "private": False,
                "sender": {"type": "agent_bot", "name": "GIA"},
                "content": "bot",
            }
        )
        is False
    )
    assert (
        is_human_public_outgoing(
            {"message": {"message_type": 0, "content": "Hola del cliente"}}
        )
        is False
    )


@pytest.mark.asyncio
async def test_list_messages_unwraps_payload():
    from app.services.chatwoot_client import ChatwootClient

    class FakeResp:
        status_code = 200
        content = b"{}"
        text = "{}"

        def json(self):
            return {
                "payload": [
                    {
                        "message_type": 1,
                        "private": False,
                        "sender": {"type": "user", "name": "Luis"},
                        "content": "Hola, soy Luis",
                    },
                    {
                        "message_type": 1,
                        "private": True,
                        "sender": {"type": "user", "name": "Luis"},
                        "content": "nota",
                    },
                    {
                        "message_type": 1,
                        "private": False,
                        "sender": {"type": "agent_bot", "name": "GIA"},
                        "content": "bot",
                    },
                ]
            }

    class FakeHTTP:
        async def get(self, url):
            return FakeResp()

    cw = ChatwootClient.__new__(ChatwootClient)
    cw._client = FakeHTTP()
    cw.settings = type("S", (), {"chatwoot_account_id": 1})()
    msgs = await cw.list_messages(9)
    assert len(msgs) == 3
    assert is_human_public_outgoing(msgs[0]) is True
    assert is_human_public_outgoing(msgs[1]) is False
    assert is_human_public_outgoing(msgs[2]) is False


def test_is_deadlock_helper():
    assert is_deadlock(Exception("deadlock detected")) is True
    assert is_deadlock(Exception("unique violation")) is False


@pytest.mark.asyncio
async def test_debounce_keeps_latest_batch(monkeypatch):
    monkeypatch.setenv("CHATWOOT_DEBOUNCE_SECONDS", "0.05")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core.agent_behavior import AgentBehavior, invalidate_agent_behavior

    invalidate_agent_behavior()
    reset_for_tests()
    behavior = AgentBehavior(
        debounce_seconds=0.05,
        reply_max_bubbles=4,
        reply_bubble_delay_ms=0,
        reply_min_seconds=0.0,
        reply_think_seconds=0.0,
        reply_chars_per_sec=100.0,
        reply_max_delay_seconds=0.0,
        sources={},
    )
    monkeypatch.setattr(
        "app.core.agent_behavior.get_agent_behavior",
        AsyncMock(return_value=behavior),
    )
    first_task = asyncio.create_task(debounce_payloads(99, {"content": "a"}))
    await asyncio.sleep(0.01)
    second_task = asyncio.create_task(debounce_payloads(99, {"content": "b"}))
    first, second = await asyncio.gather(first_task, second_task)
    assert first is None
    assert second == [{"content": "a"}, {"content": "b"}]
    reset_for_tests()
    invalidate_agent_behavior()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_agent_fail_count_resets(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    reset_for_tests()
    assert record_agent_failure(7) == 1
    assert record_agent_failure(7) == 2
    record_agent_success(7)
    assert record_agent_failure(7) == 1
    reset_for_tests()
    get_settings.cache_clear()


def test_split_reply_bubbles_only_when_model_marks():
    assert split_reply_bubbles("Solo un mensaje.") == ["Solo un mensaje."]
    # Misma idea en varios renglones: un solo mensaje.
    assert split_reply_bubbles(
        "Buen día.\n\nManejamos lámina galvanizada.\n\n¿Qué medida busca?"
    ) == ["Buen día.\n\nManejamos lámina galvanizada.\n\n¿Qué medida busca?"]
    assert split_reply_bubbles(
        "Buen día, gracias por escribir.\n---\n¿Qué calibre necesita?"
    ) == ["Buen día, gracias por escribir.", "¿Qué calibre necesita?"]
    many = split_reply_bubbles("A\n---\nB\n---\nC\n---\nD\n---\nE", max_bubbles=3)
    assert many == ["A", "B", "C\n\nD\n\nE"]


def test_first_send_wait_counts_llm_time():
    # Mínimo 8s de total; si el LLM ya tardó 2s, faltan ~6s.
    wait = first_send_wait_seconds(
        "Sí, ¿qué calibre busca?",
        elapsed=2.0,
        think=1.2,
        chars_per_sec=16.0,
        min_total=8.0,
        max_wait=16.0,
    )
    assert 5.8 <= wait <= 6.3
    # Tope 16s de total: texto largo no espera más.
    long_text = "x" * 800
    wait_long = first_send_wait_seconds(
        long_text,
        elapsed=2.0,
        think=1.2,
        chars_per_sec=16.0,
        min_total=8.0,
        max_wait=16.0,
    )
    assert wait_long == 14.0
    # LLM ya pasó el mínimo: no se añade pausa.
    assert (
        first_send_wait_seconds(
            "Ok",
            elapsed=10.0,
            think=1.2,
            chars_per_sec=16.0,
            min_total=8.0,
            max_wait=16.0,
        )
        == 0.0
    )
    gap = next_bubble_wait_seconds(
        "¿Le parece bien esa medida?",
        chars_per_sec=16.0,
        min_wait=0.7,
        max_wait=5.0,
    )
    assert 0.7 <= gap <= 3.0


@pytest.mark.asyncio
async def test_send_attachment_posts_multipart(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("CHATWOOT_ACCOUNT_ID", "1")
    monkeypatch.setenv("CHATWOOT_BASE_URL", "https://chat.example")
    monkeypatch.setenv("CHATWOOT_BOT_TOKEN", "tok")
    from app.core.config import get_settings

    get_settings.cache_clear()
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")
    posted: dict = {}

    class FakeHttp:
        async def post(self, url, **kwargs):
            posted["url"] = url
            posted["data"] = kwargs.get("data")
            posted["files"] = kwargs.get("files")
            posted["timeout"] = kwargs.get("timeout")

            class R:
                status_code = 200
                content = b'{"id": 3}'
                text = '{"id": 3}'

                def json(self):
                    return {"id": 3}

            return R()

    from app.services.chatwoot_client import ChatwootClient

    cw = ChatwootClient()
    cw._client = FakeHttp()
    data = await cw.send_attachment(
        9,
        pdf,
        content="Carta de presentación GIA",
        filename="Carta Presentación GIA.pdf",
    )
    assert data["id"] == 3
    assert posted["url"].endswith("/conversations/9/messages")
    assert posted["data"]["message_type"] == "outgoing"
    assert posted["files"]["attachments[]"][0] == "Carta Presentación GIA.pdf"
    assert posted["timeout"] == 120.0
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_signal_whatsapp_inbound_read_and_typing(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("WHATSAPP_CLOUD_ACCESS_TOKEN", "wa-token")
    monkeypatch.setenv("WHATSAPP_CLOUD_PHONE_NUMBER_ID", "123456789")
    monkeypatch.setenv("WHATSAPP_CLOUD_API_VERSION", "v26.0")
    from app.core.config import get_settings

    get_settings.cache_clear()
    posted: dict = {}

    class FakeHttp:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers=None, json=None):
            posted["url"] = url
            posted["json"] = json

            class R:
                status_code = 200
                text = "ok"

            return R()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeHttp())

    from app.services.whatsapp_read_receipt import signal_whatsapp_inbound

    ok = await signal_whatsapp_inbound(
        "wamid.test123", mark_read=True, typing_indicator=True
    )
    assert ok is True
    assert posted["url"] == "https://graph.facebook.com/v26.0/123456789/messages"
    assert posted["json"] == {
        "messaging_product": "whatsapp",
        "message_id": "wamid.test123",
        "status": "read",
        "typing_indicator": {"type": "text"},
    }
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_mark_whatsapp_message_read_posts_to_graph(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    monkeypatch.setenv("WHATSAPP_CLOUD_ACCESS_TOKEN", "wa-token")
    monkeypatch.setenv("WHATSAPP_CLOUD_PHONE_NUMBER_ID", "123456789")
    monkeypatch.setenv("WHATSAPP_CLOUD_API_VERSION", "v26.0")
    from app.core.config import get_settings

    get_settings.cache_clear()
    posted: dict = {}

    class FakeHttp:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers=None, json=None):
            posted["url"] = url
            posted["headers"] = headers
            posted["json"] = json

            class R:
                status_code = 200
                text = "ok"

            return R()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeHttp())

    from app.services.whatsapp_read_receipt import mark_whatsapp_message_read

    ok = await mark_whatsapp_message_read("wamid.test123")
    assert ok is True
    assert posted["url"] == "https://graph.facebook.com/v26.0/123456789/messages"
    assert posted["json"] == {
        "messaging_product": "whatsapp",
        "message_id": "wamid.test123",
        "status": "read",
    }
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_mark_whatsapp_message_read_skips_without_config(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("CHATWOOT_ENABLED", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    import httpx

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("no http")),
    )

    from app.services.whatsapp_read_receipt import mark_whatsapp_message_read

    assert await mark_whatsapp_message_read("wamid.test123") is False
    get_settings.cache_clear()
