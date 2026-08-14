"""Lista de modelos de chat según la llave de OpenAI o Anthropic."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Sequence, Tuple

import httpx

from app.core.llm_runtime import ANTHROPIC_MODELS, OPENAI_MODELS, LlmRuntime
from app.core.logging import get_logger

logger = get_logger(__name__)

_TIMEOUT = 8.0
_OPENAI_SKIP = (
    "embedding",
    "whisper",
    "tts",
    "dall-e",
    "audio",
    "transcribe",
    "moderation",
    "realtime",
    "sora",
    "image",
    "davinci",
    "babbage",
    "ada-",
    "text-similarity",
    "code-",
    "omni-moderation",
)
_OPENAI_KEEP = (
    "gpt-",
    "o1",
    "o3",
    "o4",
    "chatgpt-",
    "computer-use",
)


def is_openai_chat_model(model_id: str) -> bool:
    mid = (model_id or "").lower().strip()
    if not mid or mid.startswith("ft:"):
        return False
    if any(token in mid for token in _OPENAI_SKIP):
        return False
    if "luna" in mid or "sol" in mid:
        return True
    return mid.startswith(_OPENAI_KEEP)


def fallback_catalog(provider: str) -> List[Dict[str, str]]:
    ids = ANTHROPIC_MODELS if provider == "anthropic" else OPENAI_MODELS
    return [{"id": item, "label": item.split("/", 1)[-1]} for item in ids]


def ensure_current(catalog: Sequence[Dict[str, str]], current_id: str) -> List[Dict[str, str]]:
    current = (current_id or "").strip()
    items = [dict(row) for row in catalog]
    if current and all(row.get("id") != current for row in items):
        items.insert(0, {"id": current, "label": f"{current.split('/', 1)[-1]} (actual)"})
    return items


def _static(provider: str) -> Tuple[List[Dict[str, str]], str]:
    return fallback_catalog(provider), ""


async def fetch_openai_catalog(api_key: str) -> Tuple[List[Dict[str, str]], str]:
    key = (api_key or "").strip()
    if not key:
        items, _ = _static("openai")
        return items, "Guarda una llave de OpenAI para listar los modelos de esa cuenta."
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            resp.raise_for_status()
            rows = resp.json().get("data") or []
        ids = sorted(
            {
                str(row.get("id") or "").strip()
                for row in rows
                if is_openai_chat_model(str(row.get("id") or ""))
            }
        )
        items = [{"id": f"openai/{mid}", "label": mid} for mid in ids if mid]
        if not items:
            items, _ = _static("openai")
            return items, "La llave no devolvió modelos de chat; se muestra una lista de respaldo."
        return items, ""
    except Exception as exc:
        logger.warning("openai_catalog_failed", error=str(exc))
        items, _ = _static("openai")
        return items, "No se pudo consultar OpenAI; se muestra una lista de respaldo."


async def fetch_anthropic_catalog(api_key: str) -> Tuple[List[Dict[str, str]], str]:
    key = (api_key or "").strip()
    if not key:
        items, _ = _static("anthropic")
        return items, "Guarda una llave de Anthropic para listar los modelos de esa cuenta."
    try:
        items: List[Dict[str, str]] = []
        after_id = ""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for _ in range(6):
                params: Dict[str, Any] = {"limit": 100}
                if after_id:
                    params["after_id"] = after_id
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                    },
                    params=params,
                )
                resp.raise_for_status()
                payload = resp.json()
                for row in payload.get("data") or []:
                    mid = str(row.get("id") or "").strip()
                    if not mid:
                        continue
                    label = str(row.get("display_name") or "").strip() or mid
                    items.append({"id": f"anthropic/{mid}", "label": label})
                if not payload.get("has_more"):
                    break
                after_id = str(payload.get("last_id") or "").strip()
                if not after_id:
                    break
        if not items:
            items, _ = _static("anthropic")
            return items, "La llave no devolvió modelos; se muestra una lista de respaldo."
        return items, ""
    except Exception as exc:
        logger.warning("anthropic_catalog_failed", error=str(exc))
        items, _ = _static("anthropic")
        return items, "No se pudo consultar Anthropic; se muestra una lista de respaldo."


async def load_model_catalogs(runtime: LlmRuntime) -> Dict[str, Any]:
    openai_pack, anthropic_pack = await asyncio.gather(
        fetch_openai_catalog(runtime.openai_api_key),
        fetch_anthropic_catalog(runtime.anthropic_api_key),
    )
    openai_items, openai_error = openai_pack
    anthropic_items, anthropic_error = anthropic_pack
    current = runtime.agent_model
    if runtime.provider == "anthropic":
        anthropic_items = ensure_current(anthropic_items, current)
    else:
        openai_items = ensure_current(openai_items, current)
    return {
        "openai_catalog": openai_items,
        "anthropic_catalog": anthropic_items,
        "openai_catalog_error": openai_error,
        "anthropic_catalog_error": anthropic_error,
    }
