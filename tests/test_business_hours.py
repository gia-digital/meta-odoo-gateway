"""Horario laboral de ventas (orientativo)."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.business_hours import (
    HOURS_LABEL,
    check_proposed_slot,
    client_handoff_guidance,
    format_next_open,
    hours_prompt_block,
    is_within_hours,
)

TZ = ZoneInfo("America/Mexico_City")


@pytest.fixture
def settings_env(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("DISPLAY_TIMEZONE", "America/Mexico_City")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_thursday_evening_is_outside(settings_env):
    now = datetime(2026, 8, 13, 20, 0, tzinfo=TZ)
    assert is_within_hours(now) is False
    assert "FUERA" in hours_prompt_block(now)


def test_sunday_is_outside(settings_env):
    now = datetime(2026, 8, 16, 11, 0, tzinfo=TZ)
    assert is_within_hours(now) is False


def test_saturday_morning_is_inside(settings_env):
    now = datetime(2026, 8, 15, 11, 0, tzinfo=TZ)
    assert is_within_hours(now) is True
    assert "DENTRO" in hours_prompt_block(now)


def test_saturday_afternoon_is_outside(settings_env):
    now = datetime(2026, 8, 15, 14, 0, tzinfo=TZ)
    assert is_within_hours(now) is False


def test_weekday_open_and_close_edges(settings_env):
    assert is_within_hours(datetime(2026, 8, 14, 8, 0, tzinfo=TZ)) is True
    assert is_within_hours(datetime(2026, 8, 14, 7, 59, tzinfo=TZ)) is False
    assert is_within_hours(datetime(2026, 8, 14, 18, 59, tzinfo=TZ)) is True
    assert is_within_hours(datetime(2026, 8, 14, 19, 0, tzinfo=TZ)) is False


def test_handoff_guidance_never_promises_en_breve(settings_env):
    inside = client_handoff_guidance(datetime(2026, 8, 14, 10, 0, tzinfo=TZ))
    outside = client_handoff_guidance(datetime(2026, 8, 16, 10, 0, tzinfo=TZ))
    for text in (inside, outside):
        lower = text.lower()
        assert "en breve le" not in lower
        assert "le contactará en breve" not in lower
        assert "hoy mismo" not in lower
        assert "SIGUES atendiendo" in text
    assert HOURS_LABEL.split("(")[0].strip() in outside


def test_sunday_next_window_is_monday_morning(settings_env):
    now = datetime(2026, 8, 16, 11, 18, tzinfo=TZ)
    nxt = format_next_open(now)
    assert "lunes" in nxt
    assert "8:00" in nxt
    snap = hours_prompt_block(now)
    assert "CERRADA" in snap
    assert "domingo" in snap
    assert "planta" in snap.lower()


def test_proposed_sunday_afternoon_is_closed(settings_env):
    now = datetime(2026, 8, 16, 11, 18, tzinfo=TZ)
    text = check_proposed_slot(weekday="domingo", hour=15, minute=0, now=now)
    assert "FUERA" in text
    assert "lunes" in text
    assert "8:00" in text


def test_proposed_saturday_morning_is_open(settings_env):
    now = datetime(2026, 8, 16, 11, 18, tzinfo=TZ)
    text = check_proposed_slot(weekday="sábado", hour=10, minute=0, now=now)
    assert "DENTRO" in text
