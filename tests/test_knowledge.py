"""Tests del knowledge store / RAG (sin Postgres ni OpenAI)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.agent_knowledge import (
    _faq_question,
    _format_catalog,
    _format_faqs,
    resolve_agent_instructions,
    DEFAULT_AGENT_INSTRUCTIONS,
    TOOL_RULES,
)
from app.services.knowledge.ingest import chunk_text
from app.services.knowledge.retriever import RetrievedHit, format_hits, retrieve_knowledge
from app.services.knowledge.seed import faq_question
from app.services.knowledge.tools_registry import REGISTERED_TOOLS


def test_faq_question_singular_and_list():
    assert faq_question({"question": "¿Manejan inoxidable?"}) == "¿Manejan inoxidable?"
    assert _faq_question({"questions": ["Alt", "Otra"]}) == "Alt"
    assert faq_question({}) == ""


def test_format_faqs_uses_question_key():
    text = _format_faqs(
        [{"question": "¿Manejan inoxidable o aluminio?", "answer": "No."}],
        char_limit=5000,
    )
    assert "P: ¿Manejan inoxidable o aluminio?" in text
    assert "(sin pregunta)" not in text


def test_chunk_text_splits_and_overlaps():
    blob = "palabra " * 400
    chunks = chunk_text(blob, size=80, overlap=20)
    assert len(chunks) > 1
    assert chunks[0]
    assert chunk_text("corto", size=80) == ["corto"]
    assert chunk_text("   ") == []


def test_format_hits_includes_faq_policy():
    hits = [
        RetrievedHit(
            source_type="faq",
            source_id=1,
            title="¿Manejan inoxidable o aluminio?",
            text="No, únicamente acero al carbono.",
            score=1.0,
        )
    ]
    text = format_hits(hits)
    assert "inoxidable" in text.lower()
    assert "acero al carbono" in text.lower()
    assert format_hits([]) == ""


def test_format_hits_includes_product():
    hits = [
        RetrievedHit(
            source_type="product",
            source_id=3,
            title="Lámina galvanizada G60 / G90",
            text="Capa de zinc contra oxidación. Acabados G60 y G90.",
            score=1.0,
        )
    ]
    text = format_hits(hits)
    assert "Producto:" in text
    assert "G60" in text


def test_registered_tools_include_search_knowledge():
    names = {t["name"] for t in REGISTERED_TOOLS}
    assert names == {"create_lead", "escalate_to_human", "search_knowledge"}


def test_resolve_agent_instructions_uses_store_or_default():
    assert resolve_agent_instructions(None) == DEFAULT_AGENT_INSTRUCTIONS
    empty = MagicMock()
    empty.agent_instructions = "  "
    assert resolve_agent_instructions(empty) == DEFAULT_AGENT_INSTRUCTIONS
    filled = MagicMock()
    filled.agent_instructions = "Habla de tú y sé breve."
    assert resolve_agent_instructions(filled) == "Habla de tú y sé breve."
    assert "HERRAMIENTAS" in TOOL_RULES
    assert "create_lead" in TOOL_RULES


def test_seed_source_has_catalog_limits():
    from pathlib import Path
    import json

    root = Path(__file__).resolve().parents[1]
    faqs = json.loads((root / "agent_info" / "faqs.json").read_text(encoding="utf-8"))
    questions = [faq_question(item).lower() for item in faqs.get("faqs") or []]
    assert any("inoxidable" in q for q in questions)
    skills = json.loads((root / "agent_info" / "skills.json").read_text(encoding="utf-8"))
    titles = [s.get("title") for s in skills.get("skills") or []]
    assert "Límites de catálogo y transparencia" in titles
    products = json.loads((root / "agent_info" / "products.json").read_text(encoding="utf-8"))
    names = [p.get("name", "").lower() for p in products.get("products") or []]
    kinds = {p.get("kind") for p in products.get("products") or []}
    assert any("galvanizada" in n for n in names)
    assert any("kr-18" in n for n in names)
    assert any("inoxidable" in n for n in names)
    assert "product" in kinds and "service" in kinds and "out_of_catalog" in kinds


def test_format_catalog_marks_out_of_catalog():
    from types import SimpleNamespace

    products = [
        SimpleNamespace(
            active=True,
            category="aceros_planos",
            kind="product",
            name="Lámina galvanizada G60 / G90",
            summary="Capa de zinc G60 y G90.",
            details="Rollo, hoja y cinta.",
        ),
        SimpleNamespace(
            active=True,
            category="limites",
            kind="out_of_catalog",
            name="Acero inoxidable",
            summary="NO se vende.",
            details="Ofrece galvanizada.",
        ),
        SimpleNamespace(
            active=False,
            category="aceros_planos",
            kind="product",
            name="Inactivo",
            summary="No debe aparecer",
            details="",
        ),
    ]
    text = _format_catalog(products)
    assert "Lámina galvanizada G60 / G90" in text
    assert "[NO SE OFRECE]" in text
    assert "Acero inoxidable" in text
    assert "Inactivo" not in text
    assert _format_catalog([]) == ""


@pytest.mark.asyncio
async def test_retrieve_keyword_ranks_inoxidable(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.knowledge.retriever.embed_one",
        AsyncMock(return_value=None),
    )

    chunk = MagicMock()
    chunk.source_type = "faq"
    chunk.source_id = 7
    chunk.chunk_index = 0
    chunk.title = "¿Manejan inoxidable o aluminio?"
    chunk.text = "No, únicamente acero al carbono en las líneas de nuestro catálogo."

    n = {"i": 0}

    async def execute(_stmt):
        n["i"] += 1
        result = MagicMock()
        if n["i"] == 1:
            result.scalars.return_value.all.return_value = [chunk]
        else:
            result.scalars.return_value.all.return_value = [7]
        return result

    db = MagicMock()
    db.execute = execute
    hits = await retrieve_knowledge(db, "¿venden acero inoxidable?")
    assert hits
    assert "inoxidable" in hits[0].title.lower()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_knowledge_dashboard_requires_auth(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "false")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/dashboard/knowledge", follow_redirects=False)
        p = await client.get("/dashboard/knowledge/products", follow_redirects=False)
        m = await client.get("/dashboard/knowledge/model", follow_redirects=False)
    assert r.status_code == 303
    assert p.status_code == 303
    assert m.status_code == 303
    get_settings.cache_clear()
