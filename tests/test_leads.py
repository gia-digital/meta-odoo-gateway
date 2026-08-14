"""Tests de calificación de leads y gating de Odoo."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.conversation import (
    Channel,
    ConversationStatus,
    QualificationSource,
)
from app.models.schemas import LeadCreate
from app.services.conversation import ConversationService
from app.services.lead_scorer import score_conversation


def make_message(text: str, direction: str = "inbound"):
    return SimpleNamespace(
        body=text,
        direction=SimpleNamespace(value=direction),
        created_at=datetime.utcnow(),
    )


def test_lead_create_tool_schema_with_structured_fields():
    payload = LeadCreate.model_validate(
        {
            "channel": "whatsapp",
            "external_user_id": "5215512345678",
            "user_name": "Ana",
            "product_interest": "Plan Premium",
            "budget": "~5000 USD",
            "timeline": "Este mes",
            "preferred_contact_time": "Mañanas",
            "summary": "Quiere asesor",
            "reason": "Pidió cotización",
            "handed_off": True,
        }
    )
    assert payload.product_interest == "Plan Premium"
    assert payload.budget == "~5000 USD"
    assert payload.timeline == "Este mes"
    assert payload.preferred_contact_time == "Mañanas"
    assert payload.handed_off is True


def test_scoring_still_works_as_secondary_signal():
    msgs = [
        make_message("Quiero cotizar lámina galvanizada"),
        make_message("Mi presupuesto es $10,000 MXN, unas 8 toneladas"),
        make_message("Quiero hablar con un asesor"),
    ]
    result = score_conversation(msgs)
    assert result.total >= 6
    assert result.create_lead is True


@pytest.mark.asyncio
async def test_process_after_message_does_not_call_odoo_when_disabled(monkeypatch):
    monkeypatch.setenv("ODOO_ENABLED", "false")
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
async def test_qualify_lead_sets_structured_lead_fields(monkeypatch):
    monkeypatch.setenv("ODOO_ENABLED", "false")
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
        product_interest=None,
        lead_summary=None,
        budget=None,
        timeline=None,
        preferred_contact_time=None,
        user_name=None,
        user_phone=None,
        user_email=None,
        channel=Channel.whatsapp,
        external_user_id="52155",
    )

    db = AsyncMock()
    db.refresh = AsyncMock()
    service = ConversationService(db)

    result = await service.qualify_lead(
        conv,
        reason="Pidió cotización",
        user_name="Ana",
        user_phone="52155",
        handed_off=True,
        product_interest="Premium",
        summary="Quiere plan premium",
        budget="5000 USD",
        timeline="Este mes",
        preferred_contact_time="Mañanas",
    )

    assert result.status == ConversationStatus.handed_off
    assert result.qualification_source == QualificationSource.chatwoot_agent
    assert result.user_name == "Ana"
    assert result.qualification_reason == "Pidió cotización"
    assert result.product_interest == "Premium"
    assert result.lead_summary == "Quiere plan premium"
    assert result.budget == "5000 USD"
    assert result.timeline == "Este mes"
    assert result.preferred_contact_time == "Mañanas"
    assert result.qualified_at is not None
    db.commit.assert_awaited()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_create_lead_from_payload_uses_whatsapp_id_as_phone(monkeypatch):
    monkeypatch.setenv("ODOO_ENABLED", "false")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()

    conv = SimpleNamespace(
        id=9,
        messages=[],
        score=0,
        score_breakdown={},
        status=ConversationStatus.active,
        qualification_source=QualificationSource.none,
        qualification_reason=None,
        qualified_at=None,
        product_interest=None,
        lead_summary=None,
        budget=None,
        timeline=None,
        preferred_contact_time=None,
        user_name=None,
        user_phone=None,
        user_email=None,
        channel=Channel.whatsapp,
        external_user_id="5215512345678",
    )

    db = AsyncMock()
    db.refresh = AsyncMock()
    service = ConversationService(db)

    with patch.object(
        ConversationService, "get_or_create", new_callable=AsyncMock, return_value=conv
    ):
        result = await service.create_lead_from_payload(
            channel=Channel.whatsapp,
            external_user_id="5215512345678",
            user_name="Ana",
            product_interest="Plan Básico",
            handed_off=False,
        )

    assert result.product_interest == "Plan Básico"
    assert result.user_phone == "5215512345678"
    assert result.status == ConversationStatus.qualified
    assert result.qualification_source == QualificationSource.chatwoot_agent
    get_settings.cache_clear()
