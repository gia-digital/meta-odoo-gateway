"""Dashboard embebido en Chatwoot: sin token + CSP frame-ancestors."""
import pytest
from starlette.requests import Request

from app.routers.dashboard import COOKIE_NAME, is_dashboard_embed, require_dashboard_auth


def _request(
    path: str = "/dashboard/overview",
    *,
    headers: dict | None = None,
    cookies: dict | None = None,
) -> Request:
    hdrs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookies:
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
        hdrs.append((b"cookie", cookie_header.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": hdrs,
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "scheme": "https",
        "server": ("test", 443),
    }
    return Request(scope)


@pytest.fixture
def embed_settings(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv(
        "DASHBOARD_EMBED_ORIGINS",
        "https://chatwoot.init.com.mx,https://chatwoot.giacero.com",
    )
    monkeypatch.setenv("CHATWOOT_BASE_URL", "https://chatwoot.init.com.mx")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_is_dashboard_embed_chatwoot_iframe(embed_settings):
    req = _request(
        headers={
            "Referer": "https://chatwoot.init.com.mx/app/accounts/2",
            "Sec-Fetch-Dest": "iframe",
        }
    )
    assert is_dashboard_embed(req) is True


def test_is_dashboard_embed_giacero(embed_settings):
    req = _request(
        headers={
            "Referer": "https://chatwoot.giacero.com/app/accounts/1/dashboard",
            "Sec-Fetch-Dest": "iframe",
        }
    )
    assert is_dashboard_embed(req) is True


def test_is_dashboard_embed_rejects_top_level(embed_settings):
    req = _request(
        headers={
            "Referer": "https://chatwoot.init.com.mx/app/accounts/2",
            "Sec-Fetch-Dest": "document",
        }
    )
    assert is_dashboard_embed(req) is False


def test_is_dashboard_embed_rejects_other_origin(embed_settings):
    req = _request(
        headers={
            "Referer": "https://evil.example/page",
            "Sec-Fetch-Dest": "iframe",
        }
    )
    assert is_dashboard_embed(req) is False


@pytest.mark.asyncio
async def test_require_auth_allows_embed_without_cookie(embed_settings):
    req = _request(
        headers={
            "Referer": "https://chatwoot.init.com.mx/",
            "Sec-Fetch-Dest": "iframe",
        }
    )
    await require_dashboard_auth(req)
    assert req.state.set_dashboard_embed_cookie is True


@pytest.mark.asyncio
async def test_require_auth_redirects_without_embed(embed_settings):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        r = await client.get("/dashboard/knowledge", follow_redirects=False)
    assert r.status_code == 303
    assert "/dashboard" in r.headers.get("location", "")


@pytest.mark.asyncio
async def test_login_from_chatwoot_skips_token_form(embed_settings):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        r = await client.get(
            "/dashboard",
            headers={
                "Referer": "https://chatwoot.giacero.com/app/accounts/1",
                "Sec-Fetch-Dest": "iframe",
            },
            follow_redirects=False,
        )
    assert r.status_code == 303
    location = r.headers["location"]
    assert location == "/dashboard/overview" or location.endswith("/dashboard/overview")
    assert not location.startswith("http://")
    assert COOKIE_NAME in r.cookies
    csp = r.headers.get("content-security-policy", "")
    assert "frame-ancestors" in csp
    assert "https://chatwoot.init.com.mx" in csp
    assert "https://chatwoot.giacero.com" in csp
