"""Modelo y API keys: dashboard sobreescribe .env; vacío = usar el servidor."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.runtime import RuntimeSettings

logger = get_logger(__name__)

CACHE_TTL_SECONDS = 3.0

OPENAI_MODELS = (
    "openai/gpt-5.6-luna",
    "openai/gpt-4.1-mini",
)
ANTHROPIC_MODELS = (
    "anthropic/claude-sonnet-5",
    "anthropic/claude-sonnet-4-5",
    "anthropic/claude-sonnet-4-20250514",
)
SUGGESTED_MODELS = OPENAI_MODELS + ANTHROPIC_MODELS


def provider_from_model(model: str) -> str:
    lower = (model or "").lower()
    if "anthropic" in lower or "claude" in lower:
        return "anthropic"
    return "openai"


def normalize_provider(value: str, model: str = "") -> str:
    v = (value or "").strip().lower()
    if v in ("openai", "anthropic"):
        return v
    return provider_from_model(model)


def compose_agent_model(provider: str, model: str) -> str:
    raw = (model or "").strip()
    if "/" in raw:
        raw = raw.split("/", 1)[1].strip()
    provider = normalize_provider(provider, model)
    if provider == "anthropic":
        return f"anthropic/{raw}" if raw else ANTHROPIC_MODELS[0]
    return f"openai/{raw}" if raw else OPENAI_MODELS[0]

_cache_at = 0.0
_cache: Optional["LlmRuntime"] = None


@dataclass(frozen=True)
class LlmRuntime:
    provider: str
    agent_model: str
    openai_api_key: str
    anthropic_api_key: str
    agent_model_source: str
    openai_key_source: str
    anthropic_key_source: str


def mask_secret(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "••••"
    return f"{text[:4]}…{text[-4:]}"


def _pick(stored: str, env_value: str) -> tuple[str, str]:
    stored_s = (stored or "").strip()
    if stored_s:
        return stored_s, "dashboard"
    return (env_value or "").strip(), "env"


def merge_llm_runtime(row: Optional[RuntimeSettings]) -> LlmRuntime:
    env = get_settings()
    model, model_src = _pick(
        getattr(row, "agent_model", "") if row else "", env.agent_model
    )
    openai_key, openai_src = _pick(
        getattr(row, "openai_api_key", "") if row else "", env.openai_api_key
    )
    anthropic_key, anthropic_src = _pick(
        getattr(row, "anthropic_api_key", "") if row else "", env.anthropic_api_key
    )
    stored_provider = getattr(row, "llm_provider", "") if row else ""
    provider = normalize_provider(stored_provider, model or env.agent_model)
    model = compose_agent_model(provider, model or env.agent_model)
    return LlmRuntime(
        provider=provider,
        agent_model=model,
        openai_api_key=openai_key,
        anthropic_api_key=anthropic_key,
        agent_model_source=model_src if (getattr(row, "agent_model", "") if row else "") else "env",
        openai_key_source=openai_src if openai_key else "env",
        anthropic_key_source=anthropic_src if anthropic_key else "env",
    )


def next_secret(new_value: str, stored: str, *, clear: bool) -> str:
    if clear:
        return ""
    incoming = (new_value or "").strip()
    if incoming:
        return incoming
    return stored or ""


def key_status(value: str, source: str) -> str:
    masked = mask_secret(value)
    if not masked:
        return "No configurada"
    origin = "en esta pantalla" if source == "dashboard" else "desde el servidor (.env)"
    return f"Configurada {origin} ({masked})"


def public_llm_view(runtime: LlmRuntime, row: Optional[RuntimeSettings]) -> dict:
    return {
        "provider": runtime.provider,
        "agent_model": runtime.agent_model,
        "openai_status": key_status(runtime.openai_api_key, runtime.openai_key_source),
        "anthropic_status": key_status(
            runtime.anthropic_api_key, runtime.anthropic_key_source
        ),
        "has_openai_dashboard": runtime.openai_key_source == "dashboard"
        and bool(runtime.openai_api_key),
        "has_anthropic_dashboard": runtime.anthropic_key_source == "dashboard"
        and bool(runtime.anthropic_api_key),
    }


def invalidate_llm_runtime() -> None:
    global _cache, _cache_at
    _cache = None
    _cache_at = 0.0


def _remember(runtime: LlmRuntime) -> LlmRuntime:
    global _cache, _cache_at
    _cache = runtime
    _cache_at = time.monotonic()
    return runtime


async def fetch_runtime_row(db: AsyncSession) -> Optional[RuntimeSettings]:
    return (await db.execute(select(RuntimeSettings).limit(1))).scalar_one_or_none()


async def load_llm_runtime(db: AsyncSession) -> LlmRuntime:
    row = await fetch_runtime_row(db)
    return _remember(merge_llm_runtime(row))


async def get_llm_runtime(db: Optional[AsyncSession] = None) -> LlmRuntime:
    now = time.monotonic()
    if _cache is not None and now - _cache_at < CACHE_TTL_SECONDS:
        return _cache
    if db is not None:
        return await load_llm_runtime(db)
    from app.models.db import SessionLocal

    async with SessionLocal() as session:
        return await load_llm_runtime(session)


async def upsert_runtime_settings(db: AsyncSession, **fields) -> RuntimeSettings:
    row = await fetch_runtime_row(db)
    if row is None:
        row = RuntimeSettings()
        db.add(row)
    for key, val in fields.items():
        setattr(row, key, val)
    await db.commit()
    await db.refresh(row)
    invalidate_llm_runtime()
    from app.core.agent_behavior import invalidate_agent_behavior, load_agent_behavior

    invalidate_agent_behavior()
    await load_llm_runtime(db)
    await load_agent_behavior(db)
    logger.info(
        "llm_runtime_updated",
        provider=(row.llm_provider or "").strip() or "env",
        agent_model=(row.agent_model or "").strip() or "env",
        openai_key=bool((row.openai_api_key or "").strip()),
        anthropic_key=bool((row.anthropic_api_key or "").strip()),
    )
    return row
