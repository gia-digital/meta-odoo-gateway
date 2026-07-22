"""Tests de calificación por Meta Agent y gating de Odoo."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.conversation import (
    Channel,
    ConversationStatus,
    QualificationSource,
)
from app.models.schemas import MetaLeadPayload
from app.routers.meta_webhook import _parse_messenger_handovers
from app.services.conversation import ConversationService
from app.services.lead_scorer import score_conversation


def make_message(text: str, direction: str = "inbound"):
    return SimpleNamespace(
        body=text,
        direction=SimpleNamespace(value=direction),
        created_at=datetime.utcnow(),
    )


def test_meta_lead_payload_accepts_minimal():
    payload = MetaLeadPayload(
        channel="whatsapp",
        external_user_id="5215512345678",
        reason="Interés en plan premium",
    )
    assert payload.channel == "whatsapp"
    assert payload.handed_off is False
    assert payload.external_user_id == "5215512345678"


def test_meta_lead_payload_with_handoff_and_interest():
    payload = MetaLeadPayload.model_validate(
        {
            "channel": "messenger",
            "external_user_id": "psid-123",
            "user_name": "Ana",
            "product_interest": "Plan Premium",
            "handed_off": True,
            "summary": "Quiere asesor",
        }
    )
    assert payload.handed_off is True
    assert payload.product_interest == "Plan Premium"


def test_parse_messenger_pass_thread_control():
    entries = [
        {
            "messaging": [
                {
                    "sender": {"id": "USER_PSID"},
                    "recipient": {"id": "PAGE_ID"},
                    "pass_thread_control": {
                        "new_owner_app_id": "123",
                        "metadata": "customer_requested_agent",
                    },
                }
            ]
        }
    ]
    handovers = _parse_messenger_handovers(entries, channel="messenger")
    assert len(handovers) == 1
    assert handovers[0].external_user_id == "USER_PSID"
    assert "customer_requested_agent" in (handovers[0].reason or "")


def test_scoring_still_works_as_secondary_signal():
    msgs = [
        make_message("Quiero contratar el plan premium"),
        make_message("Mi presupuesto es $10,000 MXN"),
        make_message("Quiero hablar con un asesor"),
    ]
    result = score_conversation(msgs)
    assert result.total >= 6
    assert result.create_lead is True


@pytest.mark.asyncio
async def test_process_after_message_does_not_call_odoo_when_disabled(monkeypatch):
    monkeypatch.setenv("ODOO_ENABLED", "false")
    monkeypatch.setenv("META_VERIFY_TOKEN", "v")
    monkeypatch.setenv("META_APP_SECRET", "s")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()

    conv = SimpleNamespace(
        id=1,
        messages=[make_message("Hola, quiero el plan premium urgente con presupuesto")],
        score=0,
        score_breakdown={},
        odoo_lead_id=None,
        status=ConversationStatus.active,
        qualification_source=QualificationSource.none,
        channel=Channel.whatsapp,
        user_name=None,
        user_phone=None,
        user_email=None,
        external_user_id="1",
    )

    db = AsyncMock()
    service = ConversationService(db)

    with patch.object(
        ConversationService, "_create_lead_in_odoo", new_callable=AsyncMock
    ) as create_lead:
        with patch.object(
            ConversationService, "_handoff_to_human", new_callable=AsyncMock
        ) as handoff:
            await service.process_after_message(conv)
            create_lead.assert_not_called()
            handoff.assert_not_called()

    assert conv.score >= 0
    db.commit.assert_awaited()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_qualify_from_meta_sets_local_lead_fields(monkeypatch):
    monkeypatch.setenv("ODOO_ENABLED", "false")
    monkeypatch.setenv("META_VERIFY_TOKEN", "v")
    monkeypatch.setenv("META_APP_SECRET", "s")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()

    conv = SimpleNamespace(
        id=7,
        messages=[],
        score=0,
        score_breakdown={},
        status=ConversationStatus.active,
        qualification_source=QualificationSource.none,
        qualification_reason=None,
        qualified_at=None,
        user_name=None,
        user_phone=None,
        user_email=None,
        channel=Channel.whatsapp,
        external_user_id="52155",
    )

    db = AsyncMock()
    db.refresh = AsyncMock()
    service = ConversationService(db)

    result = await service.qualify_from_meta(
        conv,
        reason="Pidió cotización",
        user_name="Ana",
        user_phone="52155",
        handed_off=True,
        metadata={"product_interest": "Premium"},
    )

    assert result.status == ConversationStatus.handed_off
    assert result.qualification_source == QualificationSource.meta_agent
    assert result.user_name == "Ana"
    assert "Pidió cotización" in (result.qualification_reason or "")
    assert result.qualified_at is not None
    db.commit.assert_awaited()
    get_settings.cache_clear()
