"""Bandeja durable de webhooks de Chatwoot (un worker, sin Redis)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.conversation import InboxStatus, Message, WebhookInbox
from app.models.db import SessionLocal
from app.services.chatwoot_client import ChatwootClient, ChatwootError, ChatwootForbidden
from app.services.chatwoot_payload import (
    coerce_timestamp,
    conversation_activity_at,
    is_human_public_outgoing,
    is_incoming_message,
    is_private_message,
    message_external_id,
    message_to_webhook_payload,
)

logger = get_logger(__name__)

MAX_ATTEMPTS = 5
POLL_SECONDS = 1.0


def dedupe_key(kind: str, payload: Dict[str, Any]) -> str:
    """Clave estable: un mensaje o un cierre de ciclo, una sola fila."""
    if kind == "resolved":
        conv = payload.get("conversation")
        cid = None
        if isinstance(conv, dict):
            cid = conv.get("id") or conv.get("display_id")
        cid = cid or payload.get("conversation_id") or payload.get("id") or "unknown"
        return f"evt:conversation_resolved:{cid}"
    mid = message_external_id(payload)
    if mid:
        return f"msg:{mid}"
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()[:40]
    return f"msg:anon:{digest}"


def _backoff(attempts: int) -> datetime:
    delay = min(60, 2 ** max(attempts, 1))
    return datetime.now(timezone.utc) + timedelta(seconds=delay)


async def enqueue_webhook(
    payload: Dict[str, Any],
    *,
    kind: str,
    conversation_id: Optional[int] = None,
    attempts: int = 0,
) -> Optional[int]:
    """Inserta y hace commit. None si esa clave ya estaba en la bandeja."""
    key = dedupe_key(kind, payload)
    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(WebhookInbox)
        .values(
            dedupe_key=key,
            payload=payload,
            conversation_id=conversation_id,
            status=InboxStatus.pending.value,
            attempts=attempts,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_webhook_inbox_dedupe_key")
        .returning(WebhookInbox.id)
    )
    async with SessionLocal() as db:
        result = await db.execute(stmt)
        new_id = result.scalar_one_or_none()
        await db.commit()
        return int(new_id) if new_id is not None else None


async def claim(row_id: int) -> bool:
    """pending → processing. False si otra corrida ya la tomó."""
    async with SessionLocal() as db:
        result = await db.execute(
            update(WebhookInbox)
            .where(
                WebhookInbox.id == row_id,
                WebhookInbox.status == InboxStatus.pending.value,
            )
            .values(
                status=InboxStatus.processing.value,
                locked_at=datetime.now(timezone.utc),
            )
            .returning(WebhookInbox.id)
        )
        claimed = result.scalar_one_or_none()
        await db.commit()
        return claimed is not None


async def claim_next() -> Optional[int]:
    """Toma la fila pending más vieja que ya se puede procesar."""
    async with SessionLocal() as db:
        result = await db.execute(
            select(WebhookInbox)
            .where(
                WebhookInbox.status == InboxStatus.pending.value,
                WebhookInbox.available_at <= datetime.now(timezone.utc),
            )
            .order_by(WebhookInbox.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.status = InboxStatus.processing.value
        row.locked_at = datetime.now(timezone.utc)
        row_id = row.id
        await db.commit()
        return int(row_id)


async def load_row(row_id: int) -> Optional[WebhookInbox]:
    async with SessionLocal() as db:
        row = await db.get(WebhookInbox, row_id)
        if row is not None:
            db.expunge(row)
        return row


async def mark_done(ids: list[int]) -> None:
    if not ids:
        return
    async with SessionLocal() as db:
        await db.execute(
            update(WebhookInbox)
            .where(WebhookInbox.id.in_(ids))
            .values(
                status=InboxStatus.done.value,
                locked_at=None,
                last_error=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def _apply_failure(db: AsyncSession, row: WebhookInbox, error: str) -> None:
    row.attempts = int(row.attempts or 0) + 1
    row.last_error = (error or "")[:2000]
    row.locked_at = None
    row.updated_at = datetime.now(timezone.utc)
    if row.attempts >= MAX_ATTEMPTS:
        row.status = InboxStatus.failed.value
        row.available_at = datetime.now(timezone.utc)
    else:
        row.status = InboxStatus.pending.value
        row.available_at = _backoff(row.attempts)


async def mark_retry_many(ids: list[int], error: str) -> None:
    if not ids:
        return
    async with SessionLocal() as db:
        result = await db.execute(
            select(WebhookInbox)
            .where(
                WebhookInbox.id.in_(ids),
                WebhookInbox.status != InboxStatus.done.value,
            )
            .with_for_update()
        )
        for row in result.scalars():
            await _apply_failure(db, row, error)
        await db.commit()


async def reclaim_processing() -> int:
    """Al arrancar: lo que quedó a medias vuelve a la cola y cuenta como intento."""
    async with SessionLocal() as db:
        result = await db.execute(
            select(WebhookInbox)
            .where(WebhookInbox.status == InboxStatus.processing.value)
            .with_for_update()
        )
        rows = list(result.scalars())
        for row in rows:
            await _apply_failure(db, row, row.last_error or "reclaimed after restart")
        await db.commit()
        if rows:
            logger.info("webhook_inbox_reclaimed", count=len(rows))
        return len(rows)


async def message_already_stored(external_id: str) -> bool:
    async with SessionLocal() as db:
        found = await db.scalar(
            select(Message.id)
            .where(Message.external_message_id == external_id)
            .limit(1)
        )
        return found is not None


async def run_claimed(row_id: int) -> None:
    from app.routers.chatwoot_webhook import run_inbox_payload

    row = await load_row(row_id)
    if row is None:
        return
    payload = dict(row.payload or {})
    payload["_inbox_id"] = row.id
    payload["_inbox_attempts"] = int(row.attempts or 0)
    try:
        ids = await run_inbox_payload(payload)
    except Exception as exc:
        logger.exception(
            "webhook_inbox_process_failed", inbox_id=row_id, error=str(exc)
        )
        await mark_retry_many([row_id], str(exc))
        return
    if ids:
        await mark_done(ids)


async def process_inbox_row(row_id: int) -> None:
    """Lo llama el BackgroundTask del webhook. El worker usa claim_next."""
    if not await claim(row_id):
        return
    await run_claimed(row_id)


def _should_reconcile_message(message: Dict[str, Any]) -> bool:
    if is_private_message(message):
        return False
    if is_incoming_message(message):
        return True
    return is_human_public_outgoing(message)


async def reconcile_recent() -> None:
    """Mete en la bandeja mensajes recientes que el webhook nunca entregó."""
    settings = get_settings()
    if not settings.chatwoot_enabled:
        return
    if not settings.chatwoot_base_url or not settings.chatwoot_bot_token:
        return
    lookback = max(1, int(settings.chatwoot_reconcile_lookback_minutes))
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback)
    try:
        async with ChatwootClient() as cw:
            conversations: list[dict] = []
            for status in ("pending", "open"):
                conversations.extend(await cw.list_conversations(status=status))
            queued = 0
            for conv in conversations:
                if not isinstance(conv, dict):
                    continue
                activity = conversation_activity_at(conv)
                if activity is not None and activity < cutoff:
                    continue
                conv_id = conv.get("id")
                try:
                    conv_num = int(conv_id)
                except (TypeError, ValueError):
                    continue
                try:
                    messages = await cw.list_messages(conv_num)
                except ChatwootError as exc:
                    logger.warning(
                        "webhook_inbox_reconcile_messages_failed",
                        conversation_id=conv_num,
                        error=str(exc),
                    )
                    continue
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    created = coerce_timestamp(message.get("created_at"))
                    if created is None or created < cutoff:
                        continue
                    if not _should_reconcile_message(message):
                        continue
                    external_id = message.get("id")
                    if external_id is None:
                        continue
                    external = str(external_id)
                    if await message_already_stored(external):
                        continue
                    shaped = message_to_webhook_payload(conv, message)
                    new_id = await enqueue_webhook(
                        shaped,
                        kind="message",
                        conversation_id=conv_num,
                        attempts=1,
                    )
                    if new_id is not None:
                        queued += 1
    except ChatwootForbidden as exc:
        logger.warning("webhook_inbox_reconcile_forbidden", error=str(exc))
        return
    except ChatwootError as exc:
        logger.warning("webhook_inbox_reconcile_failed", error=str(exc))
        return
    except Exception as exc:
        logger.exception("webhook_inbox_reconcile_failed", error=str(exc))
        return
    if queued:
        logger.info("webhook_inbox_reconciled", queued=queued)


async def inbox_worker() -> None:
    """Recupera filas a medias, barre Chatwoot y procesa la cola."""
    await reclaim_processing()
    next_reconcile = 0.0
    while True:
        try:
            now = time.monotonic()
            if now >= next_reconcile:
                await reconcile_recent()
                interval = max(
                    15, int(get_settings().chatwoot_reconcile_interval_seconds)
                )
                next_reconcile = time.monotonic() + interval
            row_id = await claim_next()
            if row_id is None:
                await asyncio.sleep(POLL_SECONDS)
                continue
            await run_claimed(row_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("webhook_inbox_worker_error", error=str(exc))
            await asyncio.sleep(POLL_SECONDS)
