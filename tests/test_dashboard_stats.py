"""Tests del dashboard de estadísticas de prospectos."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.conversation import Channel, ConversationStatus, QualificationSource
from app.routers.dashboard import (
    build_lead_stats,
    build_period_choices,
    build_period_navigation,
    format_dt,
    parse_dashboard_period,
    resolve_dashboard_period,
)


def _lead(**kwargs):
    now = datetime.now(timezone.utc)
    defaults = dict(
        channel=Channel.whatsapp,
        status=ConversationStatus.qualified,
        qualification_source=QualificationSource.meta_agent,
        product_interest="Lámina galvanizada",
        budget="10 ton",
        timeline="Este mes",
        user_phone="52155",
        qualified_at=now,
        created_at=now,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_build_lead_stats_empty():
    stats = build_lead_stats([])
    assert stats["total"] == 0
    assert stats["avg_per_day"] == 0
    assert len(stats["day_labels"]) == 30
    assert sum(stats["day_values"]) == 0
    assert stats["period_key"] == "30d"


def test_build_lead_stats_aggregates():
    now = datetime.now(timezone.utc)
    leads = [
        _lead(status=ConversationStatus.qualified, product_interest="Lámina galvanizada"),
        _lead(
            status=ConversationStatus.handed_off,
            channel=Channel.messenger,
            product_interest="Tubería industrial",
            budget=None,
            timeline=None,
        ),
        _lead(
            status=ConversationStatus.qualified,
            product_interest="Lámina galvanizada G90 lisa, calibres 26 y 24, medida 4x10",
            qualified_at=now - timedelta(days=10),
            user_phone=None,
        ),
    ]
    stats = build_lead_stats(leads)
    assert stats["total"] == 3
    assert stats["qualified"] == 2
    assert stats["handed_off"] == 1
    assert stats["with_material"] == 3
    assert stats["pct_handed_off"] == 33
    assert "WhatsApp" in stats["channel_labels"]
    assert "Messenger" in stats["channel_labels"]
    materials = dict(zip(stats["material_labels"], stats["material_values"]))
    assert materials.get("Lámina galvanizada", 0) == 1
    assert materials.get("Lámina galvanizada G90", 0) == 1


def test_build_lead_stats_filters_by_month():
    now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    current = now
    previous = now - timedelta(days=40)
    leads = [
        _lead(qualified_at=current, created_at=current),
        _lead(qualified_at=previous, created_at=previous),
    ]
    month_key = "2026-08"
    period = parse_dashboard_period(month_key, now=now)
    stats = build_lead_stats(leads, period, now=now)
    assert stats["total"] == 1
    assert stats["period_key"] == month_key


def test_build_lead_stats_all_time_uses_monthly_buckets():
    now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    leads = [
        _lead(qualified_at=datetime(2026, 1, 15, tzinfo=timezone.utc)),
        _lead(qualified_at=datetime(2026, 8, 20, tzinfo=timezone.utc)),
    ]
    period = resolve_dashboard_period(parse_dashboard_period("all", now=now), leads, now=now)
    stats = build_lead_stats(leads, period, now=now)
    assert stats["period_key"] == "all"
    assert stats["day_labels"] == [
        "Enero 2026",
        "Febrero 2026",
        "Marzo 2026",
        "Abril 2026",
        "Mayo 2026",
        "Junio 2026",
        "Julio 2026",
        "Agosto 2026",
    ]
    assert stats["day_values"] == [1, 0, 0, 0, 0, 0, 0, 1]


def test_build_period_choices_includes_months():
    now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    leads = [
        _lead(qualified_at=datetime(2026, 7, 10, tzinfo=timezone.utc)),
        _lead(qualified_at=datetime(2026, 8, 20, tzinfo=timezone.utc)),
    ]
    choices = build_period_choices(leads, selected="30d", now=now)
    assert choices["selected"] == "30d"
    assert {opt["value"] for opt in choices["months"]} == {"2026-07", "2026-08"}


def test_period_navigation_for_month():
    now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    period = parse_dashboard_period("2026-08", now=now)
    nav = build_period_navigation(period, now=now)
    assert nav["prev"]["href"] == "/dashboard/overview?period=2026-07"
    assert nav["next"] is None


def test_period_navigation_for_rolling_window():
    now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    period = parse_dashboard_period("30d", now=now)
    nav = build_period_navigation(period, now=now)
    assert nav["prev"]["href"] == "/dashboard/overview?period=30d&end=2026-08-01"
    assert nav["next"] is None

    shifted = parse_dashboard_period("30d", anchor_end=date(2026, 8, 1), now=now)
    nav_shifted = build_period_navigation(shifted, now=now)
    assert nav_shifted["next"]["href"] == "/dashboard/overview?period=30d"


def test_period_navigation_disabled_for_all_time():
    now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    period = parse_dashboard_period("all", now=now)
    nav = build_period_navigation(period, now=now)
    assert nav["prev"] is None
    assert nav["next"] is None


def test_format_dt_uses_mexico_city_timezone(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("DISPLAY_TIMEZONE", "America/Mexico_City")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        utc = datetime(2026, 8, 13, 19, 0, tzinfo=timezone.utc)
        assert format_dt(utc) == "13/08/2026 13:00"
        assert format_dt(None) == "—"
    finally:
        get_settings.cache_clear()
