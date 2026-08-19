"""Runtime de modelo / API keys (dashboard sobre .env)."""
from types import SimpleNamespace

import pytest

from app.core.llm_runtime import (
    compose_agent_model,
    key_status,
    mask_secret,
    merge_llm_runtime,
    next_secret,
    normalize_provider,
    provider_from_model,
    public_llm_view,
)
from app.services.gia_agent import _resolve_api_key


def test_mask_secret():
    assert mask_secret("") == ""
    assert mask_secret("short") == "••••"
    assert mask_secret("sk-ant-abcdefghijklmnop") == "sk-a…mnop"


def test_next_secret_keeps_or_replaces_or_clears():
    assert next_secret("", "stored-key", clear=False) == "stored-key"
    assert next_secret("  new-key  ", "stored-key", clear=False) == "new-key"
    assert next_secret("new-key", "stored-key", clear=True) == ""
    assert next_secret("", "", clear=False) == ""


def test_provider_and_compose_model():
    assert provider_from_model("anthropic/claude-sonnet-5") == "anthropic"
    assert provider_from_model("openai/gpt-4.1-mini") == "openai"
    assert normalize_provider("anthropic", "openai/gpt-4.1-mini") == "anthropic"
    assert compose_agent_model("anthropic", "claude-sonnet-5") == "anthropic/claude-sonnet-5"
    assert compose_agent_model("openai", "anthropic/claude-sonnet-5") == "openai/claude-sonnet-5"
    assert compose_agent_model("anthropic", "openai/gpt-4.1-mini") == "anthropic/gpt-4.1-mini"


def test_merge_prefers_dashboard_over_env(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("AGENT_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-anthropic")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core import llm_runtime as mod

    mod.invalidate_llm_runtime()
    env_only = merge_llm_runtime(None)
    assert env_only.agent_model == "openai/gpt-4.1-mini"
    assert env_only.provider == "openai"
    assert env_only.openai_api_key == "env-openai"
    assert env_only.agent_model_source == "env"

    row = SimpleNamespace(
        agent_model="anthropic/claude-sonnet-4-5",
        llm_provider="anthropic",
        openai_api_key="",
        anthropic_api_key="dash-anthropic",
        openai_embedding_model="",
    )
    overlay = merge_llm_runtime(row)
    assert overlay.provider == "anthropic"
    assert overlay.agent_model == "anthropic/claude-sonnet-4-5"
    assert overlay.agent_model_source == "dashboard"
    assert overlay.openai_api_key == "env-openai"
    assert overlay.openai_key_source == "env"
    assert overlay.anthropic_api_key == "dash-anthropic"
    assert overlay.anthropic_key_source == "dashboard"
    view = public_llm_view(overlay, row)
    assert view["provider"] == "anthropic"
    assert "embedding_model" not in view
    assert "esta pantalla" in view["anthropic_status"]
    assert overlay.anthropic_api_key not in view["anthropic_status"]
    get_settings.cache_clear()
    mod.invalidate_llm_runtime()


def test_key_status_and_resolve(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    assert key_status("", "env") == "No configurada"
    assert "servidor" in key_status("sk-proj-abcdefghij", "env")
    runtime = merge_llm_runtime(
        SimpleNamespace(
            agent_model="anthropic/claude-sonnet-4-5",
            llm_provider="anthropic",
            openai_api_key="openai-from-dash",
            anthropic_api_key="anthropic-from-dash",
            openai_embedding_model="",
        )
    )
    assert _resolve_api_key("anthropic/claude-sonnet-4-5", runtime) == "anthropic-from-dash"
    assert _resolve_api_key("openai/gpt-4.1-mini", runtime) == "openai-from-dash"
    get_settings.cache_clear()


def test_openai_chat_filter_and_ensure_current():
    from app.services.llm_catalog import ensure_current, is_openai_chat_model

    assert is_openai_chat_model("gpt-4.1-mini")
    assert is_openai_chat_model("gpt-5.6-luna")
    assert is_openai_chat_model("o3-mini")
    assert not is_openai_chat_model("text-embedding-3-small")
    assert not is_openai_chat_model("whisper-1")
    assert not is_openai_chat_model("dall-e-3")
    catalog = ensure_current(
        [{"id": "openai/gpt-4.1-mini", "label": "gpt-4.1-mini"}],
        "openai/gpt-5.6-luna",
    )
    assert catalog[0]["id"] == "openai/gpt-5.6-luna"
    assert "actual" in catalog[0]["label"]


@pytest.mark.asyncio
async def test_catalog_without_key_uses_fallback():
    from app.services.llm_catalog import fetch_anthropic_catalog, fetch_openai_catalog

    openai_items, openai_err = await fetch_openai_catalog("")
    anthropic_items, anthropic_err = await fetch_anthropic_catalog("")
    assert openai_items
    assert anthropic_items
    assert "llave" in openai_err.lower()
    assert "llave" in anthropic_err.lower()


def test_agent_behavior_overlay_and_reset(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("CHATWOOT_REPLY_MIN_SECONDS", "8")
    monkeypatch.setenv("CHATWOOT_REPLY_MAX_DELAY_SECONDS", "16")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.core.agent_behavior import (
        merge_agent_behavior,
        parse_behavior_form,
        public_behavior_view,
    )

    env_only = merge_agent_behavior(None)
    assert env_only.reply_min_seconds == 8.0
    assert env_only.reply_max_delay_seconds == 16.0
    assert env_only.sources["reply_min_seconds"] == "env"

    row = SimpleNamespace(
        debounce_seconds=6,
        reply_max_bubbles=3,
        reply_bubble_delay_ms=None,
        reply_min_seconds=10,
        reply_think_seconds="",
        reply_chars_per_sec=20,
        reply_max_delay_seconds=14,
    )
    overlay = merge_agent_behavior(row)
    assert overlay.debounce_seconds == 6
    assert overlay.reply_min_seconds == 10
    assert overlay.reply_max_delay_seconds == 14
    assert overlay.sources["reply_min_seconds"] == "dashboard"
    assert overlay.sources["reply_think_seconds"] == "env"
    view = public_behavior_view(overlay)
    assert view["using_dashboard"] is True
    assert view["source_labels"]["reply_min_seconds"] == "esta pantalla"
    assert view["source_labels"]["reply_think_seconds"] == "servidor"
    assert view["form_values"]["debounce_seconds"] == 6
    assert view["form_values"]["reply_min_seconds"] == 10
    assert view["form_values"]["reply_think_seconds"] == ""
    assert view["form_values"]["reply_bubble_delay_ms"] == ""

    reset = parse_behavior_form({}, reset=True)
    assert reset["reply_min_seconds"] is None
    parsed = parse_behavior_form({"reply_min_seconds": "12,5", "reply_max_bubbles": "2"}, reset=False)
    assert parsed["reply_min_seconds"] == 12.5
    assert parsed["reply_max_bubbles"] == 2
    assert parsed["debounce_seconds"] is None
    get_settings.cache_clear()


def test_agent_form_renders_saved_values_in_jinja(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from jinja2 import Environment

    from app.core.agent_behavior import merge_agent_behavior, public_behavior_view

    row = SimpleNamespace(
        debounce_seconds=8,
        reply_max_bubbles=None,
        reply_bubble_delay_ms=None,
        reply_min_seconds=10,
        reply_think_seconds=None,
        reply_chars_per_sec=None,
        reply_max_delay_seconds=None,
    )
    agent = public_behavior_view(merge_agent_behavior(row))
    html = Environment().from_string(
        '<input name="debounce_seconds" value="{{ agent.form_values.debounce_seconds }}" />'
        '<input name="reply_min_seconds" value="{{ agent.form_values.reply_min_seconds }}" />'
        '<input name="reply_max_bubbles" value="{{ agent.form_values.reply_max_bubbles }}" />'
    ).render(agent=agent)
    assert 'name="debounce_seconds" value="8.0"' in html
    assert 'name="reply_min_seconds" value="10.0"' in html
    assert 'name="reply_max_bubbles" value=""' in html


def test_public_view_never_includes_raw_key(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    runtime = merge_llm_runtime(
        SimpleNamespace(
            agent_model="openai/gpt-4.1-mini",
            llm_provider="openai",
            openai_api_key="sk-proj-SUPER-SECRET-VALUE-123456",
            anthropic_api_key="",
            openai_embedding_model="",
        )
    )
    view = public_llm_view(runtime, None)
    dumped = str(view)
    assert "SUPER-SECRET-VALUE" not in dumped
    get_settings.cache_clear()
