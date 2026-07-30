"""Tests del dashboard de estadísticas de prospectos."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.conversation import Channel, ConversationStatus, QualificationSource
from app.routers.dashboard import build_lead_stats


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
    assert stats["this_week"] == 0
    assert len(stats["day_labels"]) == 30
    assert sum(stats["day_values"]) == 0


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
            product_interest="Lámina galvanizada",
            qualified_at=now - timedelta(days=10),
            user_phone=None,
        ),
    ]
    stats = build_lead_stats(leads)
    assert stats["total"] == 3
    assert stats["qualified"] == 2
    assert stats["handed_off"] == 1
    assert stats["this_week"] == 2
    assert stats["with_material"] == 3
    assert stats["pct_handed_off"] == 33
    assert "WhatsApp" in stats["channel_labels"]
    assert "Messenger" in stats["channel_labels"]
    assert stats["material_labels"][0] == "Lámina galvanizada"
    assert stats["material_values"][0] == 2
