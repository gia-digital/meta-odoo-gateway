"""Tests de seguridad: token de POST /leads."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.security import require_lead_auth


def _request(body: bytes = b"{}", headers: dict | None = None, query: str = "") -> Request:
    hdrs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/leads",
        "headers": hdrs,
        "query_string": query.encode(),
        "client": ("127.0.0.1", 12345),
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


@pytest.mark.asyncio
async def test_valid_lead_token_header(monkeypatch):
    monkeypatch.setenv("LEAD_WEBHOOK_TOKEN", "secret-lead")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    req = _request(headers={"X-Lead-Token": "secret-lead"})
    body = await require_lead_auth(req, x_lead_token="secret-lead", token=None)
    assert body == b"{}"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_valid_lead_token_query(monkeypatch):
    monkeypatch.setenv("LEAD_WEBHOOK_TOKEN", "secret-lead")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    req = _request(query="token=secret-lead")
    body = await require_lead_auth(req, x_lead_token=None, token="secret-lead")
    assert body == b"{}"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_invalid_lead_token_fails(monkeypatch):
    monkeypatch.setenv("LEAD_WEBHOOK_TOKEN", "secret-lead")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    req = _request(headers={"X-Lead-Token": "wrong"})
    with pytest.raises(HTTPException) as exc:
        await require_lead_auth(req, x_lead_token="wrong", token=None)
    assert exc.value.status_code == 401
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_missing_lead_token_config_fails(monkeypatch):
    monkeypatch.setenv("LEAD_WEBHOOK_TOKEN", "")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    req = _request(headers={"X-Lead-Token": "anything"})
    with pytest.raises(HTTPException) as exc:
        await require_lead_auth(req, x_lead_token="anything", token=None)
    assert exc.value.status_code == 401
    get_settings.cache_clear()
