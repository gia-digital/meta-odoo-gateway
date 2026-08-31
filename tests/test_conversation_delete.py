"""Eliminar conversaciones (pruebas / admin)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.conversation import Channel, ConversationStatus
from app.services.conversation import ConversationService


@pytest.mark.asyncio
async def test_delete_conversation_removes_row():
    db = MagicMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    conv = MagicMock()
    conv.id = 99

    service = ConversationService(db)
    await service.delete_conversation(conv)

    db.delete.assert_awaited_once_with(conv)
    db.commit.assert_awaited_once()
