"""Guards in-process para un solo worker (droplet 1 GB: sin Redis)."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from app.core.logging import get_logger

logger = get_logger(__name__)

_fail_counts: Dict[int, int] = defaultdict(int)
_buffers: Dict[int, List[dict]] = defaultdict(list)
_tokens: Dict[int, int] = defaultdict(int)
_lock = asyncio.Lock()
_human_replied: Set[int] = set()
_last_inbound_wamid: Dict[int, str] = {}


def record_inbound_wamid(cw_id: int, wamid: Optional[str]) -> None:
    """Último wamid entrante por hilo (read receipt cuando responde un humano)."""
    if wamid:
        _last_inbound_wamid[cw_id] = wamid


def last_inbound_wamid(cw_id: int) -> Optional[str]:
    return _last_inbound_wamid.get(cw_id)


def record_agent_success(cw_id: int) -> None:
    _fail_counts.pop(cw_id, None)


def record_agent_failure(cw_id: int) -> int:
    _fail_counts[cw_id] += 1
    return _fail_counts[cw_id]


def agent_fail_count(cw_id: int) -> int:
    return int(_fail_counts.get(cw_id, 0))


def is_agent_error_reason(reason: Optional[str]) -> bool:
    return bool(reason) and str(reason).startswith("agent_error:")


def record_human_reply(cw_id: int) -> None:
    """Mute in-process: un humano ya escribió al cliente."""
    _human_replied.add(cw_id)


def clear_human_reply_guard(cw_id: int) -> None:
    _human_replied.discard(cw_id)


def human_has_replied(cw_id: int) -> bool:
    return cw_id in _human_replied


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


def reset_for_tests() -> None:
    _fail_counts.clear()
    _buffers.clear()
    _tokens.clear()
    _human_replied.clear()
    _last_inbound_wamid.clear()
