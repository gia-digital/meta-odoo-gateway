"""GET /health: 200 con la base arriba, 503 si no responde."""
import asyncio
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient


class _FakeConn:
    def __init__(self, error: BaseException | None, delay: float):
        self.error = error
        self.delay = delay

    async def execute(self, _stmt):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error


class _FakeEngine:
    def __init__(self, error: BaseException | None = None, delay: float = 0):
        self.conn = _FakeConn(error, delay)

    @asynccontextmanager
    async def connect(self):
        yield self.conn


async def _get_health():
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health")


@pytest.fixture(autouse=True)
def _reset_probe(monkeypatch):
    from app.routers import health

    monkeypatch.setattr(health, "_probe", None)


@pytest.mark.asyncio
async def test_health_ok(monkeypatch):
    from app.routers import health

    monkeypatch.setattr(health, "engine", _FakeEngine())
    r = await _get_health()
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok"}


@pytest.mark.asyncio
async def test_health_db_down(monkeypatch):
    from app.routers import health

    monkeypatch.setattr(health, "engine", _FakeEngine(error=ConnectionRefusedError()))
    r = await _get_health()
    assert r.status_code == 503
    assert r.json()["database"] == "unreachable"


@pytest.mark.asyncio
async def test_health_db_timeout(monkeypatch):
    from app.routers import health

    engine = _FakeEngine(delay=0.3)
    monkeypatch.setattr(health, "DB_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(health, "engine", engine)
    r = await _get_health()
    assert r.status_code == 503

    # Mientras el ping colgado sigue en curso, no se abre otro.
    first_probe = health._probe
    r = await _get_health()
    assert r.status_code == 503
    assert health._probe is first_probe

    await asyncio.sleep(0.35)
    monkeypatch.setattr(health, "DB_TIMEOUT_SECONDS", 1)
    r = await _get_health()
    assert r.status_code == 200
