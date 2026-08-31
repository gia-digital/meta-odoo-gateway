"""Importa agent_info/ (dir o ZIP) hacia el knowledge store (sobrescribe)."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.knowledge import KnowledgeFaq, KnowledgeProduct, KnowledgeSkill
from app.services.agent_knowledge import invalidate_instructions_cache
from app.services.knowledge.ingest import ingest_file
from app.services.knowledge.product_specs import merge_specs_into_products
from app.services.knowledge.seed import faq_question
from app.services.knowledge.store import KnowledgeStore

logger = get_logger(__name__)

Bundle = Dict[str, Any]


def _read_json_bytes(raw: bytes) -> Dict[str, Any]:
    return json.loads(raw.decode("utf-8"))


def _load_json_file(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundle_from_dir(base: Path) -> Bundle:
    """Carga JSON (+ instrucciones) desde un directorio tipo agent_info/."""
    base = Path(base)
    business = _load_json_file(base / "business_info.json") or {}
    instructions_md = base / "agent_instructions.md"
    if instructions_md.is_file():
        text_body = instructions_md.read_text(encoding="utf-8").strip()
        if text_body:
            business = dict(business)
            business["agent_instructions"] = text_body
    files_dir = base / "files"
    file_blobs: List[Tuple[str, bytes]] = []
    if files_dir.is_dir():
        for path in sorted(files_dir.iterdir()):
            if path.is_file() and not path.name.endswith(".MISSING.txt"):
                file_blobs.append((path.name, path.read_bytes()))
    # PDFs sueltos en la raíz (agent_info clásico)
    for path in sorted(base.glob("*.pdf")):
        if path.is_file():
            file_blobs.append((path.name, path.read_bytes()))
    return {
        "business_info": business,
        "faqs": _load_json_file(base / "faqs.json") or {"faqs": []},
        "skills": _load_json_file(base / "skills.json") or {"skills": []},
        "products": merge_specs_into_products(
            _load_json_file(base / "products.json") or {"products": []}
        ),
        "file_blobs": file_blobs,
    }


def load_bundle_from_zip(data: bytes) -> Bundle:
    """Carga un ZIP exportado (o empaquetado a mano con los mismos nombres)."""
    business: Dict[str, Any] = {}
    faqs: Dict[str, Any] = {"faqs": []}
    skills: Dict[str, Any] = {"skills": []}
    products: Dict[str, Any] = {"products": []}
    file_blobs: List[Tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = {n: n for n in zf.namelist()}

        def _pick(*candidates: str) -> Optional[str]:
            for c in candidates:
                if c in names:
                    return c
                # zip con carpeta raíz
                for n in names:
                    if n.endswith("/" + c) or n.endswith(c):
                        if Path(n).name == c:
                            return n
            return None

        bi = _pick("business_info.json")
        if bi:
            business = _read_json_bytes(zf.read(bi))
        fq = _pick("faqs.json")
        if fq:
            faqs = _read_json_bytes(zf.read(fq))
        sk = _pick("skills.json")
        if sk:
            skills = _read_json_bytes(zf.read(sk))
        pr = _pick("products.json")
        if pr:
            products = _read_json_bytes(zf.read(pr))

        instr = _pick("agent_instructions.md")
        if instr:
            text_body = zf.read(instr).decode("utf-8").strip()
            if text_body:
                business = dict(business)
                business["agent_instructions"] = text_body

        for name in zf.namelist():
            if name.endswith("/") or name.endswith(".MISSING.txt"):
                continue
            parts = Path(name).parts
            if "files" in parts:
                fname = Path(name).name
                if fname:
                    file_blobs.append((fname, zf.read(name)))
            elif name.lower().endswith(".pdf") and Path(name).name == Path(name).parts[-1]:
                file_blobs.append((Path(name).name, zf.read(name)))

    return {
        "business_info": business or {},
        "faqs": faqs,
        "skills": skills,
        "products": products,
        "file_blobs": file_blobs,
    }


def _payload_business(data: Dict[str, Any]) -> Dict[str, str]:
    payload = data.get("payload") or data
    contact = payload.get("contact_info") or {}
    fields = {
        "business_description": str(payload.get("business_description") or ""),
        "purchase_info": str(payload.get("purchase_info") or ""),
        "payment_method": str(payload.get("payment_method") or ""),
        "delivery_and_shipping": str(payload.get("delivery_and_shipping") or ""),
        "return_policy": str(payload.get("return_policy") or ""),
        "email": str(contact.get("email") or payload.get("email") or ""),
        "hours_of_operation": str(
            contact.get("hours_of_operation") or payload.get("hours_of_operation") or ""
        ),
        "address": str(contact.get("address") or payload.get("address") or ""),
    }
    instructions = (data.get("agent_instructions") or "").strip()
    if instructions:
        fields["agent_instructions"] = instructions
    return fields


async def import_agent_info_bundle(
    db: AsyncSession,
    bundle: Bundle,
    *,
    include_files: bool = False,
    deactivate_missing: bool = False,
) -> Dict[str, int]:
    """Upsert business/FAQs/skills/products (y opcionalmente archivos) desde un bundle."""
    store = KnowledgeStore(db)
    result = {
        "business": 0,
        "faqs_upserted": 0,
        "skills_upserted": 0,
        "products_upserted": 0,
        "faqs_deactivated": 0,
        "skills_deactivated": 0,
        "products_deactivated": 0,
        "files_upserted": 0,
    }

    try:
        await db.execute(text("SELECT pg_advisory_lock(872365)"))
    except Exception:
        pass

    try:
        business_data = bundle.get("business_info") or {}
        if business_data:
            fields = _payload_business(business_data)
            if any(v for k, v in fields.items() if k != "agent_instructions") or fields.get(
                "agent_instructions"
            ):
                await store.upsert_business(**fields)
                result["business"] = 1

        # --- FAQs ---
        faq_items = (bundle.get("faqs") or {}).get("faqs") or []
        existing_faqs = await store.list_faqs(include_inactive=True)
        by_q = {(f.question or "").strip().casefold(): f for f in existing_faqs}
        seen_q: set[str] = set()
        for item in faq_items:
            question = faq_question(item)
            answer = (item.get("answer") or "").strip()
            if not question or not answer:
                continue
            key = question.casefold()
            seen_q.add(key)
            meta = item.get("metadata") or {}
            category = str(meta.get("category") or item.get("category") or "")
            active = item.get("active")
            if active is None:
                active = meta.get("active")
            active_bool = True if active is None else bool(active)
            row = by_q.get(key)
            if row is None:
                row = KnowledgeFaq(source="import")
                by_q[key] = row
            else:
                row.source = "import"
            row.question = question
            row.answer = answer
            row.category = category
            row.active = active_bool
            await store.save_faq(row)
            result["faqs_upserted"] += 1

        if deactivate_missing:
            for row in existing_faqs:
                key = (row.question or "").strip().casefold()
                if key and key not in seen_q and row.active:
                    row.active = False
                    row.source = "import"
                    await store.save_faq(row)
                    result["faqs_deactivated"] += 1

        # --- Skills ---
        skill_items = (bundle.get("skills") or {}).get("skills") or []
        existing_skills = await store.list_skills(include_inactive=True)
        by_title = {s.title: s for s in existing_skills}
        seen_titles: set[str] = set()
        for item in skill_items:
            title = (item.get("title") or "").strip()
            legacy = (item.get("legacy_title") or "").strip()
            if not title:
                continue
            body = (item.get("skill") or "").strip()
            when = (item.get("description") or item.get("when_to_apply") or "").strip()
            active = item.get("active")
            active_bool = True if active is None else bool(active)
            row = by_title.get(title) or (by_title.get(legacy) if legacy else None)
            if row is None:
                row = KnowledgeSkill(source="import")
            else:
                # Import fuerza el contenido del repo; deja de ser "manual" libre.
                row.source = "import"
            row.title = title
            row.when_to_apply = when
            row.body = body
            row.active = active_bool
            await store.save_skill(row)
            by_title[title] = row
            seen_titles.add(title)
            if legacy:
                seen_titles.add(legacy)
            result["skills_upserted"] += 1

        if deactivate_missing:
            for row in existing_skills:
                if row.title not in seen_titles and row.active:
                    row.active = False
                    row.source = "import"
                    await store.save_skill(row)
                    result["skills_deactivated"] += 1

        # --- Products ---
        product_items = (bundle.get("products") or {}).get("products") or []
        existing_products = await store.list_products(include_inactive=True)
        by_name = {(p.name or "").strip().casefold(): p for p in existing_products}
        seen_names: set[str] = set()
        for item in product_items:
            name = (item.get("name") or "").strip()
            if not name:
                continue
            key = name.casefold()
            seen_names.add(key)
            active = item.get("active")
            active_bool = True if active is None else bool(active)
            row = by_name.get(key)
            if row is None:
                row = KnowledgeProduct(source="import")
                by_name[key] = row
            else:
                row.source = "import"
            row.name = name
            row.kind = (item.get("kind") or "product").strip() or "product"
            row.category = (item.get("category") or "").strip()
            row.summary = (item.get("summary") or "").strip()
            row.details = (item.get("details") or "").strip()
            row.aliases = (item.get("aliases") or "").strip()
            try:
                row.sort_order = int(item.get("sort_order") or 0)
            except (TypeError, ValueError):
                row.sort_order = 0
            row.active = active_bool
            await store.save_product(row)
            result["products_upserted"] += 1

        if deactivate_missing:
            for row in existing_products:
                key = (row.name or "").strip().casefold()
                if key and key not in seen_names and row.active:
                    row.active = False
                    row.source = "import"
                    await store.save_product(row)
                    result["products_deactivated"] += 1

        # --- Files (opcionales) ---
        if include_files:
            from app.models.knowledge import KnowledgeFile
            from app.services.knowledge.ingest import uploads_dir

            existing_files = await store.list_files()
            by_fname = {(f.filename or "").casefold(): f for f in existing_files}
            for fname, blob in bundle.get("file_blobs") or []:
                safe = Path(fname).name
                if not safe or not blob:
                    continue
                dest_name = f"{uuid4().hex[:10]}_{safe}"
                dest = uploads_dir() / dest_name
                dest.write_bytes(blob)
                row = by_fname.get(safe.casefold())
                if row is None:
                    row = KnowledgeFile(
                        filename=safe,
                        stored_path=str(dest),
                        mime="application/pdf" if safe.lower().endswith(".pdf") else "",
                        byte_size=len(blob),
                        status="pending",
                        active=True,
                        source="import",
                    )
                else:
                    old = Path(row.stored_path or "")
                    row.stored_path = str(dest)
                    row.byte_size = len(blob)
                    row.status = "pending"
                    row.source = "import"
                    row.active = True
                    try:
                        if old.is_file() and old.resolve() != dest.resolve():
                            old.unlink()
                    except OSError:
                        pass
                await store.save_file(row)
                await ingest_file(db, row)
                by_fname[safe.casefold()] = row
                result["files_upserted"] += 1

        invalidate_instructions_cache()
    finally:
        try:
            await db.execute(text("SELECT pg_advisory_unlock(872365)"))
        except Exception:
            pass

    logger.info("knowledge_import_done", **result)
    return result
