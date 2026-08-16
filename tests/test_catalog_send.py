"""Envío del catálogo GIA: PDF, tool y Chatwoot multipart."""
from __future__ import annotations

import unicodedata
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.agent_knowledge import TOOL_RULES, build_agent_instructions, invalidate_instructions_cache
from app.services.catalog_document import (
    CATALOG_CAPTION,
    CATALOG_FILENAME,
    deliver_catalog,
    find_catalog_file_row,
    is_catalog_filename,
    resolve_catalog_path,
)
from app.services.chatwoot_client import ChatwootClient, ChatwootError
from app.services.knowledge.tools_registry import REGISTERED_TOOLS


WHATSAPP_DOCUMENT_MAX_BYTES = 100 * 1024 * 1024


def _chatwoot_env(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("CHATWOOT_ACCOUNT_ID", "1")
    monkeypatch.setenv("CHATWOOT_BASE_URL", "https://chat.example")
    monkeypatch.setenv("CHATWOOT_BOT_TOKEN", "tok")
    from app.core.config import get_settings

    get_settings.cache_clear()
    return get_settings


def test_catalog_filename_rejects_corporate_pdf():
    assert is_catalog_filename("Carta Presentación GIA.pdf") is True
    assert is_catalog_filename("carta presentacion gia.PDF") is True
    nfd = unicodedata.normalize("NFD", "Carta Presentación GIA.pdf")
    assert nfd != "Carta Presentación GIA.pdf"
    assert is_catalog_filename(nfd) is True
    assert is_catalog_filename("Presentación GIA.pdf") is False
    assert is_catalog_filename("Presentacion GIA.pdf") is False
    assert is_catalog_filename("lista-precios.pdf") is False


def test_catalog_pdf_exists_and_is_within_whatsapp_limit():
    path = resolve_catalog_path()
    assert path is not None
    assert path.is_file()
    assert is_catalog_filename(path.name)
    size = path.stat().st_size
    assert size > 1000
    assert size < WHATSAPP_DOCUMENT_MAX_BYTES
    with path.open("rb") as fh:
        assert fh.read(5).startswith(b"%PDF")


def test_resolve_catalog_path_prefers_stored_file(tmp_path):
    stored = tmp_path / "Carta Presentación GIA.pdf"
    stored.write_bytes(b"%PDF-1.4 stored")
    found = resolve_catalog_path(str(stored))
    assert found == stored


def test_tool_contract_includes_send_catalog():
    names = {t["name"] for t in REGISTERED_TOOLS}
    assert "send_catalog" in names
    assert "send_catalog" in TOOL_RULES
    assert "lista de precios" in TOOL_RULES.lower()
    when = next(t["when"] for t in REGISTERED_TOOLS if t["name"] == "send_catalog")
    assert "carta de presentación" in when.lower()


def test_build_tools_registers_send_catalog():
    from app.services.gia_agent import _build_tools

    names = [t.name for t in _build_tools()]
    assert names == [
        "create_lead",
        "escalate_to_human",
        "search_knowledge",
        "send_catalog",
    ]


@pytest.mark.asyncio
async def test_find_catalog_file_row_prefers_active(monkeypatch):
    corporate = MagicMock(
        filename="Presentación GIA.pdf", active=True, stored_path="/corp.pdf"
    )
    inactive = MagicMock(
        filename="Carta Presentación GIA.pdf",
        active=False,
        stored_path="/old.pdf",
    )
    active = MagicMock(
        filename="Carta Presentación GIA.pdf",
        active=True,
        stored_path="/live.pdf",
    )
    store = MagicMock()
    store.list_files = AsyncMock(return_value=[corporate, inactive, active])
    monkeypatch.setattr(
        "app.services.catalog_document.KnowledgeStore",
        lambda _db: store,
    )
    row = await find_catalog_file_row(MagicMock())
    assert row is active


@pytest.mark.asyncio
async def test_build_agent_instructions_include_send_catalog(monkeypatch):
    invalidate_instructions_cache()
    store = MagicMock()
    store.get_business = AsyncMock(return_value=None)
    store.list_skills = AsyncMock(return_value=[])
    store.list_products = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "app.services.agent_knowledge.KnowledgeStore",
        lambda _db: store,
    )
    text = await build_agent_instructions(MagicMock())
    invalidate_instructions_cache()
    assert "send_catalog" in text
    assert "Carta de Presentación GIA" in text or "carta de presentación" in text.lower()


@pytest.mark.asyncio
async def test_send_attachment_multipart_body(monkeypatch, tmp_path):
    _chatwoot_env(monkeypatch)
    pdf = tmp_path / "doc.pdf"
    payload = b"%PDF-1.4 catalog-bytes"
    pdf.write_bytes(payload)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers.get("content-type", "")
        captured["body"] = request.content
        captured["json_header"] = request.headers.get("content-type", "").startswith(
            "application/json"
        )
        return httpx.Response(200, json={"id": 99})

    client = httpx.AsyncClient(
        base_url="https://chat.example",
        transport=httpx.MockTransport(handler),
        headers={"api_access_token": "tok"},
    )
    cw = ChatwootClient()
    cw._client = client
    try:
        data = await cw.send_attachment(
            9,
            pdf,
            content=CATALOG_CAPTION,
            filename=CATALOG_FILENAME,
        )
    finally:
        await client.aclose()
        from app.core.config import get_settings

        get_settings.cache_clear()

    assert data["id"] == 99
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/v1/accounts/1/conversations/9/messages")
    assert captured["json_header"] is False
    assert "multipart/form-data" in captured["content_type"]
    body = captured["body"]
    assert b'name="attachments[]"' in body
    assert payload in body
    assert CATALOG_FILENAME.encode() in body
    assert b'name="content"' in body
    assert CATALOG_CAPTION.encode() in body
    assert b'name="message_type"' in body
    assert b"outgoing" in body


@pytest.mark.asyncio
async def test_send_attachment_missing_file_does_not_post(monkeypatch, tmp_path):
    _chatwoot_env(monkeypatch)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"id": 1})

    client = httpx.AsyncClient(
        base_url="https://chat.example",
        transport=httpx.MockTransport(handler),
    )
    cw = ChatwootClient()
    cw._client = client
    missing = tmp_path / "no-existe.pdf"
    try:
        with pytest.raises(ChatwootError, match="attachment missing"):
            await cw.send_attachment(1, missing)
        assert calls["n"] == 0
    finally:
        await client.aclose()
        from app.core.config import get_settings

        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_send_attachment_does_not_retry_client_error(monkeypatch, tmp_path):
    _chatwoot_env(monkeypatch)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(413, text="Payload too large")

    client = httpx.AsyncClient(
        base_url="https://chat.example",
        transport=httpx.MockTransport(handler),
    )
    cw = ChatwootClient()
    cw._client = client
    try:
        with pytest.raises(ChatwootError, match="413"):
            await cw.send_attachment(1, pdf, filename=CATALOG_FILENAME)
        assert calls["n"] == 1
    finally:
        await client.aclose()
        from app.core.config import get_settings

        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_send_attachment_retries_server_error(monkeypatch, tmp_path):
    _chatwoot_env(monkeypatch)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"id": 7})

    client = httpx.AsyncClient(
        base_url="https://chat.example",
        transport=httpx.MockTransport(handler),
    )
    from tenacity import wait_none

    cw = ChatwootClient()
    cw._client = client
    retry = cw._post_attachment.retry
    original_wait = retry.wait
    retry.wait = wait_none()
    try:
        data = await cw.send_attachment(1, pdf, filename=CATALOG_FILENAME)
        assert data["id"] == 7
        assert calls["n"] == 3
    finally:
        retry.wait = original_wait
        await client.aclose()
        from app.core.config import get_settings

        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_deliver_catalog_uses_caption_and_blocks_second_send(monkeypatch, tmp_path):
    pdf = tmp_path / CATALOG_FILENAME
    pdf.write_bytes(b"%PDF-1.4 test")
    monkeypatch.setattr(
        "app.services.catalog_document.find_catalog_pdf",
        AsyncMock(return_value=pdf),
    )
    sent: list[dict] = []

    class FakeCW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def send_attachment(self, cid, path, content="", filename=None, mime="application/pdf"):
            sent.append(
                {
                    "cid": cid,
                    "path": path,
                    "content": content,
                    "filename": filename,
                    "mime": mime,
                }
            )
            return {"id": 11}

    monkeypatch.setattr("app.services.chatwoot_client.ChatwootClient", FakeCW)
    bot = SimpleNamespace(db=MagicMock(), chatwoot_conversation_id=42, extra={})
    msg = await deliver_catalog(bot)
    assert "enviado" in msg.lower()
    assert sent[0]["content"] == CATALOG_CAPTION
    assert sent[0]["filename"] == CATALOG_FILENAME
    assert sent[0]["mime"] == "application/pdf"
    again = await deliver_catalog(bot)
    assert "ya se envió" in again.lower()
    assert len(sent) == 1
