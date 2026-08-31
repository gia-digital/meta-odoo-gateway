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
    assert names == {
        "create_lead",
        "escalate_to_human",
        "search_knowledge",
        "send_catalog",
        "check_sales_hours",
    }


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
    assert "send_catalog" in TOOL_RULES
    assert "check_sales_hours" in TOOL_RULES


def test_catalog_filename_is_carta_not_corporate():
    from app.services.catalog_document import is_catalog_filename, resolve_catalog_path

    assert is_catalog_filename("Carta Presentación GIA.pdf") is True
    assert is_catalog_filename("carta presentacion gia.PDF") is True
    assert is_catalog_filename("Presentación GIA.pdf") is False
    assert is_catalog_filename("Presentacion GIA.pdf") is False
    path = resolve_catalog_path()
    assert path is not None
    assert path.is_file()
    assert is_catalog_filename(path.name)


@pytest.mark.asyncio
async def test_deliver_catalog_sends_once(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace

    from app.services.catalog_document import CATALOG_FILENAME, deliver_catalog
    from app.services.chatwoot_client import ChatwootError

    pdf = tmp_path / CATALOG_FILENAME
    pdf.write_bytes(b"%PDF-1.4 test")
    monkeypatch.setattr(
        "app.services.catalog_document.find_catalog_pdf",
        AsyncMock(return_value=pdf),
    )
    sent: list[dict] = []

    class FakeCW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def send_attachment(self, cid, path, content="", filename=None, mime="application/pdf"):
            sent.append(
                {"cid": cid, "path": path, "content": content, "filename": filename}
            )
            return {"id": 11}

    monkeypatch.setattr("app.services.chatwoot_client.ChatwootClient", FakeCW)
    bot = SimpleNamespace(db=MagicMock(), chatwoot_conversation_id=42, extra={})
    msg = await deliver_catalog(bot)
    assert "enviado" in msg.lower()
    assert sent == [
        {
            "cid": 42,
            "path": pdf,
            "content": "Carta de presentación GIA",
            "filename": CATALOG_FILENAME,
        }
    ]
    again = await deliver_catalog(bot)
    assert "ya se envió" in again.lower()
    assert len(sent) == 1

    monkeypatch.setattr(
        "app.services.catalog_document.find_catalog_pdf",
        AsyncMock(return_value=None),
    )
    missing = await deliver_catalog(SimpleNamespace(db=MagicMock(), extra={}))
    assert "no se encontró" in missing.lower()

    monkeypatch.setattr(
        "app.services.catalog_document.find_catalog_pdf",
        AsyncMock(return_value=pdf),
    )

    async def boom(*args, **kwargs):
        raise ChatwootError("upload failed")

    FakeCW.send_attachment = boom
    failed = await deliver_catalog(
        SimpleNamespace(db=MagicMock(), chatwoot_conversation_id=1, extra={})
    )
    assert "no se pudo adjuntar" in failed.lower()
    assert "send_catalog" in TOOL_RULES


def test_seed_source_has_catalog_limits():
    from pathlib import Path
    import json

    root = Path(__file__).resolve().parents[1]
    faqs = json.loads((root / "agent_info" / "faqs.json").read_text(encoding="utf-8"))
    questions = [faq_question(item).lower() for item in faqs.get("faqs") or []]
    assert any("inoxidable" in q for q in questions)
    assert any("carta de presentación" in q for q in questions)
    assert any("cerquero" in q for q in questions)
    assert any("cédula" in q or "cedula" in q for q in questions)
    assert any("distribuidor" in q for q in questions)
    menudeo = next(
        f for f in faqs["faqs"] if "menudeo" in faq_question(f).lower()
    )
    assert "distribuidor" not in menudeo["answer"].lower()

    skills = json.loads((root / "agent_info" / "skills.json").read_text(encoding="utf-8"))
    titles = [s.get("title") for s in skills.get("skills") or []]
    assert "Límites de catálogo y transparencia" in titles
    assert "Enviar catálogo / carta de presentación" in titles
    limits = next(s for s in skills["skills"] if s["title"] == "Límites de catálogo y transparencia")
    body = limits["skill"].lower()
    assert "prohibido recomendar distribuidores" in body
    assert "cerquero" in body
    assert "cédula" in body or "cedula" in body
    assert '3"' in limits["skill"] or "3″" in limits["skill"] or "3 pulg" in body
    assert "asesor" in body and "menudeo" in body

    products = json.loads((root / "agent_info" / "products.json").read_text(encoding="utf-8"))
    names = [p.get("name", "").lower() for p in products.get("products") or []]
    kinds = {p.get("kind") for p in products.get("products") or []}
    assert any("galvanizada" in n for n in names)
    assert any("kr-18" in n for n in names)
    assert any("inoxidable" in n for n in names)
    assert any("cerquero" in n for n in names)
    assert any("macizo" in n for n in names)
    assert any("cédula" in n or "cedula" in n for n in names)
    assert "product" in kinds and "service" in kinds and "out_of_catalog" in kinds

    tuberia = next(p for p in products["products"] if "tubería industrial" in p["name"].lower())
    assert "cédula" not in (tuberia.get("aliases") or "").lower()
    assert "3" in (tuberia.get("summary") or "")


def test_product_specs_cover_anexo_a():
    from app.services.knowledge.product_specs import (
        load_product_specs,
        merge_specs_into_products,
        specs_to_product_items,
    )

    specs = load_product_specs()
    assert specs.get("specs")
    items = specs_to_product_items(specs)
    names = [i["name"] for i in items]
    assert any("planos" in n.lower() for n in names)
    assert any("tubería" in n.lower() and "redonda" in n.lower() for n in names)
    assert any("acanalada" in n.lower() for n in names)

    planos = next(i for i in items if i.get("spec_id") == "planos_hojas")
    assert "28" in planos["summary"]
    assert "40" in planos["details"]  # ejemplo de calibre no manejado
    assert "6.35" in planos["details"]

    merged = merge_specs_into_products({"products": []})
    assert len(merged["products"]) == len(items)
    assert "agent_info/product_specs.json" in merged["generated_from"]

    from pathlib import Path
    import json

    base = json.loads(
        (Path(__file__).resolve().parents[1] / "agent_info" / "products.json").read_text(
            encoding="utf-8"
        )
    )
    enriched = merge_specs_into_products(base)
    cr = next(
        p for p in enriched["products"] if "fría recocida" in (p.get("name") or "").lower()
    )
    assert "CALIBRES Y ESPECIFICACIONES" in cr.get("details", "")
    assert "28" in cr.get("summary", "")


@pytest.mark.asyncio
async def test_product_index_chunks_long_details(monkeypatch):
    from app.services.knowledge.store import KnowledgeStore

    captured: list[list[str]] = []

    async def fake_delete(self, *args, **kwargs):
        return None

    async def fake_insert(self, *, texts, **kwargs):
        captured.append(list(texts))

    monkeypatch.setattr(KnowledgeStore, "_delete_chunks", fake_delete)
    monkeypatch.setattr(KnowledgeStore, "_insert_chunks", fake_insert)

    product = type("P", (), {
        "id": 1, "active": True, "name": "Spec", "kind": "product",
        "category": "especificaciones", "summary": "s", "aliases": "",
        "details": "x" * 4000,
    })()

    await KnowledgeStore(None).index_product(product)
    assert captured
    assert len(captured[0]) > 1


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
        e = await client.get("/dashboard/knowledge/export", follow_redirects=False)
    assert r.status_code == 303
    assert p.status_code == 303
    assert m.status_code == 303
    assert e.status_code == 303
    get_settings.cache_clear()


def test_export_serializers_match_agent_info_shape():
    import io
    import zipfile

    from app.services.knowledge.export import (
        business_to_agent_info,
        build_export_zip,
        faqs_to_agent_info,
        products_to_agent_info,
        skills_to_agent_info,
    )

    biz = MagicMock()
    biz.business_description = "GIA"
    biz.purchase_info = "Mayoreo"
    biz.payment_method = "Transferencia"
    biz.delivery_and_shipping = "3-4 días"
    biz.return_policy = "Inspección"
    biz.email = "a@b.com"
    biz.hours_of_operation = "L-V"
    biz.address = "Ecatepec"
    biz.agent_instructions = "Habla de usted."

    faq = MagicMock()
    faq.question = "¿Pedido mínimo?"
    faq.answer = "1 ton / 3 ton"
    faq.category = "compra_precios"
    faq.active = True
    faq.source = "manual"

    skill = MagicMock()
    skill.title = "Política de precios"
    skill.when_to_apply = "Cuando preguntan precio"
    skill.body = "No inventes descuentos"
    skill.active = True
    skill.source = "seed"

    product = MagicMock()
    product.name = "Lámina HR"
    product.kind = "product"
    product.category = "aceros_planos"
    product.sort_order = 10
    product.aliases = "HR"
    product.summary = "Caliente"
    product.details = "Detalle"
    product.active = True
    product.source = "seed"

    bi = business_to_agent_info(biz)
    assert bi["payload"]["business_description"] == "GIA"
    assert bi["agent_instructions"] == "Habla de usted."
    assert bi["payload"]["contact_info"]["email"] == "a@b.com"

    assert faqs_to_agent_info([faq])["faqs"][0]["question"] == "¿Pedido mínimo?"
    assert skills_to_agent_info([skill])["skills"][0]["skill"] == "No inventes descuentos"
    assert products_to_agent_info([product])["products"][0]["name"] == "Lámina HR"

    zip_bytes = build_export_zip(
        {
            "exported_at": "2026-08-21T12:00:00+00:00",
            "business_info": bi,
            "faqs": faqs_to_agent_info([faq]),
            "skills": skills_to_agent_info([skill]),
            "products": products_to_agent_info([product]),
            "files_manifest": {"files": []},
            "file_rows": [],
        }
    )
    assert zip_bytes[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        assert "faqs.json" in names
        assert "skills.json" in names
        assert "products.json" in names
        assert "business_info.json" in names
        assert "agent_instructions.md" in names


def test_agent_info_forbids_agent_prices():
    """Regresión: skills/FAQs no deben invitar al agente a cotizar."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "agent_info"
    skills = json.loads((root / "skills.json").read_text(encoding="utf-8"))
    pricing = next(s for s in skills["skills"] if s["title"] == "Política de precios")
    body = pricing["skill"].lower()
    assert "nunca des precios" in body or "prohibido absoluto" in body
    assert "el precio se lo confirma un asesor" in body

    faqs = json.loads((root / "faqs.json").read_text(encoding="utf-8"))
    by_q = {f["question"]: f["answer"].lower() for f in faqs["faqs"]}
    assert "yo no doy precios" in by_q["¿Cuánto cuesta / me da el precio?"]
    assert "asesor" in by_q["¿Tienen lista de precios?"]
    assert "con gusto se la comparto" not in by_q["¿Tienen lista de precios?"]


def test_load_bundle_from_dir_and_zip_roundtrip(tmp_path):
    from pathlib import Path

    from app.services.knowledge.export import build_export_zip
    from app.services.knowledge.import_agent_info import (
        load_bundle_from_dir,
        load_bundle_from_zip,
    )

    root = Path(__file__).resolve().parents[1] / "agent_info"
    bundle = load_bundle_from_dir(root)
    assert bundle["faqs"]["faqs"]
    assert bundle["skills"]["skills"]
    assert (bundle["business_info"].get("payload") or {}).get("business_description")
    assert any(
        "planos" in (p.get("name") or "").lower()
        for p in bundle["products"].get("products") or []
    )

    zip_bytes = build_export_zip(
        {
            "exported_at": "2026-08-21T12:00:00+00:00",
            "business_info": {
                **bundle["business_info"],
                "agent_instructions": "NUNCA des precios.",
            },
            "faqs": bundle["faqs"],
            "skills": bundle["skills"],
            "products": bundle["products"],
            "files_manifest": {"files": []},
            "file_rows": [],
        }
    )
    loaded = load_bundle_from_zip(zip_bytes)
    assert loaded["business_info"]["agent_instructions"] == "NUNCA des precios."
    assert len(loaded["faqs"]["faqs"]) == len(bundle["faqs"]["faqs"])
    assert any(
        "nunca" in (s.get("skill") or "").lower()
        for s in loaded["skills"]["skills"]
        if s.get("title") == "Política de precios"
    )


@pytest.mark.asyncio
async def test_import_bundle_upserts_without_db(monkeypatch):
    from app.services.knowledge import import_agent_info as mod

    saved_faqs = []
    saved_skills = []
    saved_products = []
    business_fields = {}

    class FakeStore:
        def __init__(self, db):
            self.db = db

        async def upsert_business(self, **fields):
            business_fields.update(fields)
            return MagicMock()

        async def list_faqs(self, include_inactive=True):
            return []

        async def save_faq(self, faq):
            saved_faqs.append(faq)
            return faq

        async def list_skills(self, include_inactive=True):
            return []

        async def save_skill(self, skill):
            saved_skills.append(skill)
            return skill

        async def list_products(self, include_inactive=True):
            return []

        async def save_product(self, product):
            saved_products.append(product)
            return product

        async def list_files(self):
            return []

    monkeypatch.setattr(mod, "KnowledgeStore", FakeStore)
    monkeypatch.setattr(mod, "invalidate_instructions_cache", lambda: None)

    db = AsyncMock()
    db.execute = AsyncMock()

    bundle = {
        "business_info": {
            "payload": {
                "business_description": "GIA",
                "purchase_info": "Mayoreo",
                "payment_method": "",
                "delivery_and_shipping": "",
                "return_policy": "",
                "contact_info": {"email": "a@b.com", "hours_of_operation": "", "address": ""},
            },
            "agent_instructions": "NUNCA des precios.",
        },
        "faqs": {
            "faqs": [
                {
                    "question": "¿Cuánto cuesta / me da el precio?",
                    "answer": "El precio se lo confirma directamente un asesor.",
                    "metadata": {"category": "compra_precios"},
                }
            ]
        },
        "skills": {
            "skills": [
                {
                    "title": "Política de precios",
                    "description": "Cuando preguntan precio",
                    "skill": "PROHIBIDO ABSOLUTO — NUNCA des precios.",
                }
            ]
        },
        "products": {
            "products": [
                {
                    "name": "Lámina HR",
                    "kind": "product",
                    "category": "aceros_planos",
                    "summary": "Caliente",
                    "details": "Detalle",
                }
            ]
        },
        "file_blobs": [],
    }
    result = await mod.import_agent_info_bundle(db, bundle)
    assert result["business"] == 1
    assert result["faqs_upserted"] == 1
    assert result["skills_upserted"] == 1
    assert result["products_upserted"] == 1
    assert business_fields["agent_instructions"] == "NUNCA des precios."
    assert "asesor" in saved_faqs[0].answer.lower()
    assert "nunca des precios" in saved_skills[0].body.lower()
    assert saved_products[0].name == "Lámina HR"


@pytest.mark.asyncio
async def test_knowledge_import_requires_auth(monkeypatch):
    monkeypatch.setenv("CHATWOOT_ENABLED", "false")
    monkeypatch.setenv("ADMIN_API_TOKEN", "admin")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/dashboard/knowledge/import", follow_redirects=False)
    assert r.status_code == 303
    get_settings.cache_clear()
