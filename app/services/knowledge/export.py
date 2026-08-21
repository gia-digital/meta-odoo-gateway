"""Exporta el knowledge de Postgres al formato agent_info/ (JSON + ZIP)."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    KnowledgeBusiness,
    KnowledgeFaq,
    KnowledgeFile,
    KnowledgeProduct,
    KnowledgeSkill,
)
from app.services.knowledge.store import KnowledgeStore

EXPORT_NOTES = (
    "Exportado desde el knowledge store en vivo (Postgres). "
    "Sustituye los JSON de agent_info/ en el repo; los PDFs van en files/."
)


def _json_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def business_to_agent_info(row: Optional[KnowledgeBusiness]) -> Dict[str, Any]:
    if row is None:
        return {
            "generated_from": ["knowledge_business (vacío)"],
            "notes": EXPORT_NOTES,
            "payload": {
                "business_description": "",
                "purchase_info": "",
                "payment_method": "",
                "delivery_and_shipping": "",
                "return_policy": "",
                "contact_info": {
                    "email": "",
                    "hours_of_operation": "",
                    "address": "",
                },
            },
        }
    return {
        "generated_from": ["knowledge_business"],
        "notes": EXPORT_NOTES,
        "payload": {
            "business_description": row.business_description or "",
            "purchase_info": row.purchase_info or "",
            "payment_method": row.payment_method or "",
            "delivery_and_shipping": row.delivery_and_shipping or "",
            "return_policy": row.return_policy or "",
            "contact_info": {
                "email": row.email or "",
                "hours_of_operation": row.hours_of_operation or "",
                "address": row.address or "",
            },
        },
        "agent_instructions": (getattr(row, "agent_instructions", None) or "").strip(),
    }


def faqs_to_agent_info(faqs: Sequence[KnowledgeFaq]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for faq in faqs:
        item: Dict[str, Any] = {
            "question": faq.question or "",
            "answer": faq.answer or "",
            "metadata": {
                "category": faq.category or "",
                "active": bool(faq.active),
                "source": faq.source or "",
            },
        }
        items.append(item)
    return {
        "generated_from": ["knowledge_faqs"],
        "notes": EXPORT_NOTES,
        "faqs": items,
    }


def skills_to_agent_info(skills: Sequence[KnowledgeSkill]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for skill in skills:
        items.append(
            {
                "title": skill.title or "",
                "description": skill.when_to_apply or "",
                "skill": skill.body or "",
                "active": bool(skill.active),
                "source": skill.source or "",
            }
        )
    return {
        "generated_from": ["knowledge_skills"],
        "notes": EXPORT_NOTES,
        "skills": items,
    }


def products_to_agent_info(products: Sequence[KnowledgeProduct]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for product in products:
        items.append(
            {
                "name": product.name or "",
                "kind": product.kind or "product",
                "category": product.category or "",
                "sort_order": int(product.sort_order or 0),
                "aliases": product.aliases or "",
                "summary": product.summary or "",
                "details": product.details or "",
                "active": bool(product.active),
                "source": product.source or "",
            }
        )
    return {
        "generated_from": ["knowledge_products"],
        "notes": EXPORT_NOTES,
        "products": items,
    }


def files_manifest(files: Sequence[KnowledgeFile]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for f in files:
        items.append(
            {
                "id": f.id,
                "filename": f.filename,
                "mime": f.mime or "",
                "byte_size": int(f.byte_size or 0),
                "status": f.status or "",
                "active": bool(f.active),
                "source": f.source or "",
                "zip_path": f"files/{f.filename}",
            }
        )
    return {
        "generated_from": ["knowledge_files"],
        "notes": EXPORT_NOTES,
        "files": items,
    }


async def collect_agent_info_export(db: AsyncSession) -> Dict[str, Any]:
    """Snapshot listo para ZIP / escritura a disco."""
    store = KnowledgeStore(db)
    business = await store.get_business()
    faqs = await store.list_faqs(include_inactive=True)
    skills = await store.list_skills()
    products = await store.list_products()
    files = await store.list_files()
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "business_info": business_to_agent_info(business),
        "faqs": faqs_to_agent_info(faqs),
        "skills": skills_to_agent_info(skills),
        "products": products_to_agent_info(products),
        "files_manifest": files_manifest(files),
        "file_rows": files,
    }


def build_export_zip(snapshot: Dict[str, Any]) -> bytes:
    """ZIP con business_info.json, faqs.json, skills.json, products.json y files/."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("business_info.json", _json_bytes(snapshot["business_info"]))
        zf.writestr("faqs.json", _json_bytes(snapshot["faqs"]))
        zf.writestr("skills.json", _json_bytes(snapshot["skills"]))
        zf.writestr("products.json", _json_bytes(snapshot["products"]))
        zf.writestr("files.json", _json_bytes(snapshot["files_manifest"]))
        instructions = (snapshot["business_info"].get("agent_instructions") or "").strip()
        if instructions:
            zf.writestr("agent_instructions.md", instructions.encode("utf-8") + b"\n")
        used_names: set[str] = set()
        for row in snapshot.get("file_rows") or []:
            name = Path(row.filename or "archivo").name
            if not name:
                continue
            dest = name
            if dest in used_names:
                dest = f"{row.id}_{name}"
            used_names.add(dest)
            path = Path(row.stored_path or "")
            if path.is_file():
                zf.write(path, arcname=f"files/{dest}")
            else:
                zf.writestr(
                    f"files/{dest}.MISSING.txt",
                    f"Archivo no encontrado en el servidor: {row.stored_path}\n".encode(
                        "utf-8"
                    ),
                )
        zf.writestr(
            "README_EXPORT.txt",
            (
                "Export del knowledge store GIA\n"
                f"Fecha: {snapshot.get('exported_at')}\n\n"
                "Copia business_info.json, faqs.json, skills.json y products.json a agent_info/.\n"
                "Los PDFs están en files/. agent_instructions.md es el texto de /dashboard/knowledge/instructions.\n"
                "Nota: el seed al boot NO sobrescribe FAQs/productos ya existentes; skills con source=seed sí se refrescan.\n"
            ).encode("utf-8"),
        )
    return buf.getvalue()


async def write_export_to_dir(db: AsyncSession, out_dir: Path) -> Dict[str, int]:
    """Escribe el snapshot en un directorio (útil en el servidor vía CLI)."""
    snapshot = await collect_agent_info_export(db)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "business_info.json").write_bytes(_json_bytes(snapshot["business_info"]))
    (out_dir / "faqs.json").write_bytes(_json_bytes(snapshot["faqs"]))
    (out_dir / "skills.json").write_bytes(_json_bytes(snapshot["skills"]))
    (out_dir / "products.json").write_bytes(_json_bytes(snapshot["products"]))
    (out_dir / "files.json").write_bytes(_json_bytes(snapshot["files_manifest"]))
    instructions = (snapshot["business_info"].get("agent_instructions") or "").strip()
    if instructions:
        (out_dir / "agent_instructions.md").write_text(instructions + "\n", encoding="utf-8")
    files_dir = out_dir / "files"
    files_dir.mkdir(exist_ok=True)
    copied = 0
    used_names: set[str] = set()
    for row in snapshot.get("file_rows") or []:
        name = Path(row.filename or "archivo").name
        if not name:
            continue
        dest_name = name if name not in used_names else f"{row.id}_{name}"
        used_names.add(dest_name)
        src = Path(row.stored_path or "")
        if src.is_file():
            (files_dir / dest_name).write_bytes(src.read_bytes())
            copied += 1
    return {
        "faqs": len(snapshot["faqs"]["faqs"]),
        "skills": len(snapshot["skills"]["skills"]),
        "products": len(snapshot["products"]["products"]),
        "files_copied": copied,
    }
