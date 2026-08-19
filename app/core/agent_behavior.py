"""Comportamiento del agente: dashboard sobreescribe .env; vacío = servidor."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.runtime import RuntimeSettings

logger = get_logger(__name__)

CACHE_TTL_SECONDS = 3.0

# nombre en RuntimeSettings → atributo en Settings
_FIELDS = (
    ("debounce_seconds", "chatwoot_debounce_seconds", float),
    ("reply_max_bubbles", "chatwoot_reply_max_bubbles", int),
    ("reply_bubble_delay_ms", "chatwoot_reply_bubble_delay_ms", int),
    ("reply_min_seconds", "chatwoot_reply_min_seconds", float),
    ("reply_think_seconds", "chatwoot_reply_think_seconds", float),
    ("reply_chars_per_sec", "chatwoot_reply_chars_per_sec", float),
    ("reply_max_delay_seconds", "chatwoot_reply_max_delay_seconds", float),
)

_cache_at = 0.0
_cache: Optional["AgentBehavior"] = None


@dataclass(frozen=True)
class AgentBehavior:
    debounce_seconds: float
    reply_max_bubbles: int
    reply_bubble_delay_ms: int
    reply_min_seconds: float
    reply_think_seconds: float
    reply_chars_per_sec: float
    reply_max_delay_seconds: float
    sources: dict


def _as_number(raw: Any, kind):
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip().replace(",", ".")
        if not raw:
            return None
    try:
        return kind(raw)
    except (TypeError, ValueError):
        return None


def env_defaults() -> dict:
    env = get_settings()
    return {name: getattr(env, env_name) for name, env_name, _ in _FIELDS}


def merge_agent_behavior(row: Optional[RuntimeSettings]) -> AgentBehavior:
    defaults = env_defaults()
    values = {}
    sources = {}
    for name, _env_name, kind in _FIELDS:
        stored = _as_number(getattr(row, name, None) if row else None, kind)
        if stored is None:
            values[name] = kind(defaults[name])
            sources[name] = "env"
        else:
            values[name] = stored
            sources[name] = "dashboard"
    min_s = float(values["reply_min_seconds"])
    max_s = float(values["reply_max_delay_seconds"])
    if max_s < min_s:
        values["reply_max_delay_seconds"] = min_s
    values["reply_max_bubbles"] = max(1, min(8, int(values["reply_max_bubbles"])))
    values["debounce_seconds"] = max(0.0, float(values["debounce_seconds"]))
    values["reply_chars_per_sec"] = max(1.0, float(values["reply_chars_per_sec"]))
    return AgentBehavior(sources=sources, **values)


def public_behavior_view(behavior: AgentBehavior) -> dict:
    defaults = env_defaults()
    using_dashboard = any(src == "dashboard" for src in behavior.sources.values())
    # Vacío en el form = usar default del .env. Evitar clave "values": Jinja2 la
    # confunde con dict.values() y deja los inputs en blanco.
    form_values = {
        name: getattr(behavior, name) if behavior.sources[name] == "dashboard" else ""
        for name, _, _ in _FIELDS
    }
    return {
        "form_values": form_values,
        "defaults": defaults,
        "sources": behavior.sources,
        "source_labels": {
            key: ("esta pantalla" if src == "dashboard" else "servidor")
            for key, src in behavior.sources.items()
        },
        "using_dashboard": using_dashboard,
    }


def parse_behavior_form(form: dict, *, reset: bool) -> dict:
    """None = volver al default del .env para ese campo."""
    if reset:
        return {name: None for name, _, _ in _FIELDS}
    out = {}
    for name, _, kind in _FIELDS:
        out[name] = _as_number(form.get(name), kind)
    return out


def invalidate_agent_behavior() -> None:
    global _cache, _cache_at
    _cache = None
    _cache_at = 0.0


def _remember(behavior: AgentBehavior) -> AgentBehavior:
    global _cache, _cache_at
    _cache = behavior
    _cache_at = time.monotonic()
    return behavior


async def load_agent_behavior(db: AsyncSession) -> AgentBehavior:
    from app.core.llm_runtime import fetch_runtime_row

    try:
        row = await fetch_runtime_row(db)
        return _remember(merge_agent_behavior(row))
    except Exception as exc:
        logger.warning("agent_behavior_load_failed", error=str(exc))
        return _remember(merge_agent_behavior(None))


async def get_agent_behavior(db: Optional[AsyncSession] = None) -> AgentBehavior:
    now = time.monotonic()
    if _cache is not None and now - _cache_at < CACHE_TTL_SECONDS:
        return _cache
    if db is not None:
        return await load_agent_behavior(db)
    try:
        from app.models.db import SessionLocal

        async with SessionLocal() as session:
            return await load_agent_behavior(session)
    except Exception as exc:
        logger.warning("agent_behavior_session_failed", error=str(exc))
        return _remember(merge_agent_behavior(None))
