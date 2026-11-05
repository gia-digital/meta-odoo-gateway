"""Perfil de contacto estable entre ciclos."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.conversation import Channel
from app.services.contact_profile import (
    apply_profile_to_conversation,
    format_known_contact_block,
    sync_conversation_contact_fields,
)


def test_format_known_contact_block_empty():
    assert format_known_contact_block() == ""
    assert format_known_contact_block(user_name="  ") == ""


def test_format_known_contact_block_lists_fields():
    text = format_known_contact_block(
        user_name="Ana",
        user_company="Aceros del Norte",
        user_phone="5215512345678",
        user_email="ana@example.com",
    )
    assert "Nombre: Ana" in text
    assert "Empresa: Aceros del Norte" in text
    assert "Teléfono: 5215512345678" in text
    assert "Correo: ana@example.com" in text
    assert "confirma en corto" in text


def test_apply_profile_fills_blanks_only():
    conv = SimpleNamespace(
        user_name=None,
        user_company=None,
        user_phone="52155",
        user_email=None,
    )
    profile = SimpleNamespace(
        display_name="Ana",
        company="GIA Cliente",
        phone="999",
        email="ana@example.com",
    )
    apply_profile_to_conversation(conv, profile)
    assert conv.user_name == "Ana"
    assert conv.user_company == "GIA Cliente"
    assert conv.user_phone == "52155"
    assert conv.user_email == "ana@example.com"


def test_sync_conversation_contact_fields_clips():
    conv = SimpleNamespace(
        user_name=None, user_company=None, user_phone=None, user_email=None
    )
    sync_conversation_contact_fields(
        conv,
        user_name="  Ana  ",
        user_company="  Acme SA  ",
        user_phone=" 52155 ",
        user_email=" ana@x.com ",
    )
    assert conv.user_name == "Ana"
    assert conv.user_company == "Acme SA"
    assert conv.user_phone == "52155"
    assert conv.user_email == "ana@x.com"


@pytest.mark.asyncio
async def test_upsert_contact_profile_creates_and_updates(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings
    from app.services import contact_profile as cp

    get_settings.cache_clear()
    db = MagicMock()
    db.add = MagicMock()
    db.refresh = AsyncMock()
    commits: list = []

    async def fake_commit(session):
        commits.append(session)

    monkeypatch.setattr(cp, "commit_with_retry", fake_commit)
    monkeypatch.setattr(cp, "get_contact_profile", AsyncMock(return_value=None))

    created = await cp.upsert_contact_profile(
        db,
        channel=Channel.whatsapp,
        external_user_id="5215512345678",
        display_name="Ana",
        company="Acme",
        phone="5215512345678",
        email="ana@example.com",
    )
    assert created.display_name == "Ana"
    assert created.company == "Acme"
    db.add.assert_called_once()
    assert commits
    db.refresh.assert_awaited()

    existing = SimpleNamespace(
        display_name="Ana",
        company="Acme",
        phone="5215512345678",
        email="ana@example.com",
    )
    monkeypatch.setattr(cp, "get_contact_profile", AsyncMock(return_value=existing))
    commits.clear()
    db.refresh.reset_mock()
    updated = await cp.upsert_contact_profile(
        db,
        channel=Channel.whatsapp,
        external_user_id="5215512345678",
        company="Acme Norte",
        display_name="",
    )
    assert updated.company == "Acme Norte"
    assert updated.display_name == "Ana"
    assert commits
    db.refresh.assert_awaited()
    get_settings.cache_clear()
