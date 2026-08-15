"""Guards in-process para un solo worker (droplet 1 GB: sin Redis)."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_fail_counts: Dict[int, int] = defaultdict(int)
_buffers: Dict[int, List[dict]] = defaultdict(list)
_tokens: Dict[int, int] = defaultdict(int)
_lock = asyncio.Lock()
_resume_tasks: Dict[int, asyncio.Task] = {}


def record_agent_success(cw_id: int) -> None:
    _fail_counts.pop(cw_id, None)


def record_agent_failure(cw_id: int) -> int:
    _fail_counts[cw_id] += 1
    return _fail_counts[cw_id]


def agent_fail_count(cw_id: int) -> int:
    return int(_fail_counts.get(cw_id, 0))


def is_agent_error_reason(reason: Optional[str]) -> bool:
    return bool(reason) and str(reason).startswith("agent_error:")


def is_stale_handoff(
    handed_off_at: Optional[datetime],
    *,
    now: Optional[datetime] = None,
    minutes: Optional[int] = None,
) -> bool:
    """True si el handoff ya superó la ventana para que un humano tome el hilo."""
    settings = get_settings()
    window = settings.chatwoot_handoff_resume_minutes if minutes is None else minutes
    if window <= 0:
        return False
    # Sin timestamp (hilos viejos): tratar como vencido para no dejarlos mudos.
    if handed_off_at is None:
        return True
    current = now or datetime.now(timezone.utc)
    ts = handed_off_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return current - ts >= timedelta(minutes=window)


async def debounce_payloads(cw_id: int, payload: dict) -> Optional[List[dict]]:
    """Agrupa webhooks del mismo hilo. None = llegó uno más nuevo, no procesar."""
    from app.core.agent_behavior import get_agent_behavior

    behavior = await get_agent_behavior()
    wait = max(0.0, float(behavior.debounce_seconds))
    async with _lock:
        _buffers[cw_id].append(payload)
        _tokens[cw_id] += 1
        my_token = _tokens[cw_id]
    if wait:
        await asyncio.sleep(wait)
    async with _lock:
        if _tokens.get(cw_id) != my_token:
            return None
        batch = _buffers.pop(cw_id, [])
        _tokens.pop(cw_id, None)
        return batch


def has_newer_inbound(cw_id: int) -> bool:
    """True si llegó otro mensaje del cliente mientras este turno pensaba."""
    return cw_id in _tokens


def schedule_handoff_resume(cw_id: int) -> None:
    """Best-effort: si nadie asigna el hilo, volver a pending. Muere con el proceso."""
    settings = get_settings()
    minutes = int(settings.chatwoot_handoff_resume_minutes)
    if minutes <= 0:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    old = _resume_tasks.pop(cw_id, None)
    if old and not old.done():
        old.cancel()
    _resume_tasks[cw_id] = loop.create_task(
        _resume_if_unassigned(cw_id, minutes),
        name=f"chatwoot-resume-{cw_id}",
    )


async def _resume_if_unassigned(cw_id: int, minutes: int) -> None:
    try:
        await asyncio.sleep(max(1, minutes) * 60)
        from app.services.chatwoot_client import ChatwootClient

        async with ChatwootClient() as cw:
            changed = await cw.return_to_pending_if_unassigned(cw_id)
            if changed:
                try:
                    await cw.send_message(
                        cw_id,
                        (
                            "Bot retomó el hilo: nadie lo asignó a tiempo. "
                            "El siguiente mensaje del cliente lo atiende el agente."
                        ),
                        private=True,
                    )
                except Exception as note_exc:
                    logger.error(
                        "chatwoot_resume_note_failed",
                        conversation_id=cw_id,
                        error=str(note_exc),
                    )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error(
            "chatwoot_auto_resume_failed",
            conversation_id=cw_id,
            error=str(exc),
        )
    finally:
        current = _resume_tasks.get(cw_id)
        if current is asyncio.current_task():
            _resume_tasks.pop(cw_id, None)


def reset_for_tests() -> None:
    _fail_counts.clear()
    _buffers.clear()
    _tokens.clear()
    for task in list(_resume_tasks.values()):
        task.cancel()
    _resume_tasks.clear()
