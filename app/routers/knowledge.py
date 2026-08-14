"""Dashboard de knowledge (CRUD + visibilidad del RAG)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.db import get_db
from app.models.knowledge import KnowledgeFaq, KnowledgeFile, KnowledgeSkill
from app.routers.dashboard import require_dashboard_auth, templates
from app.services.agent_knowledge import invalidate_instructions_cache
from app.services.knowledge.ingest import ingest_file, uploads_dir
from app.services.knowledge.store import KnowledgeStore
from app.services.knowledge.tools_registry import REGISTERED_TOOLS

router = APIRouter(prefix="/dashboard/knowledge", tags=["knowledge"], include_in_schema=False)

ALLOWED_UPLOAD = {".pdf", ".txt", ".md", ".markdown"}


def _redirect(tab: str, notice: str = "") -> RedirectResponse:
    url = f"/dashboard/knowledge/{tab}"
    if notice:
        url += f"?notice={notice}"
    return RedirectResponse(url=url, status_code=303)


@router.get("", response_class=HTMLResponse, name="dashboard_knowledge")
@router.get("/", response_class=HTMLResponse, name="dashboard_knowledge_slash")
async def knowledge_overview(
    request: Request,
    notice: str = "",
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    store = KnowledgeStore(db)
    stats = await store.stats()
    settings = get_settings()
    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
            "tab": "overview",
            "active_nav": "knowledge",
            "stats": stats,
            "settings": settings,
            "notice": notice,
            "tools": REGISTERED_TOOLS,
        },
    )


@router.get("/business", response_class=HTMLResponse, name="dashboard_knowledge_business")
async def knowledge_business(
    request: Request,
    notice: str = "",
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    store = KnowledgeStore(db)
    row = await store.get_business()
    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
            "tab": "business",
            "active_nav": "knowledge",
            "business": row,
            "notice": notice,
        },
    )


@router.post("/business", name="dashboard_knowledge_business_save")
async def knowledge_business_save(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
    business_description: str = Form(""),
    purchase_info: str = Form(""),
    payment_method: str = Form(""),
    delivery_and_shipping: str = Form(""),
    return_policy: str = Form(""),
    email: str = Form(""),
    hours_of_operation: str = Form(""),
    address: str = Form(""),
):
    store = KnowledgeStore(db)
    await store.upsert_business(
        business_description=business_description,
        purchase_info=purchase_info,
        payment_method=payment_method,
        delivery_and_shipping=delivery_and_shipping,
        return_policy=return_policy,
        email=email,
        hours_of_operation=hours_of_operation,
        address=address,
    )
    invalidate_instructions_cache()
    return _redirect("business", "Negocio actualizado")


@router.get("/instructions", response_class=HTMLResponse, name="dashboard_knowledge_instructions")
async def knowledge_instructions(
    request: Request,
    notice: str = "",
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    from app.services.agent_knowledge import resolve_agent_instructions

    store = KnowledgeStore(db)
    row = await store.get_business()
    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
            "tab": "instructions",
            "active_nav": "knowledge",
            "agent_instructions": resolve_agent_instructions(row),
            "using_default": not bool(
                row and (getattr(row, "agent_instructions", None) or "").strip()
            ),
            "notice": notice,
        },
    )


@router.post("/instructions", name="dashboard_knowledge_instructions_save")
async def knowledge_instructions_save(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
    agent_instructions: str = Form(""),
):
    store = KnowledgeStore(db)
    await store.upsert_business(agent_instructions=agent_instructions.strip())
    invalidate_instructions_cache()
    return _redirect("instructions", "Instrucciones actualizadas")


@router.get("/faqs", response_class=HTMLResponse, name="dashboard_knowledge_faqs")
async def knowledge_faqs(
    request: Request,
    q: str = "",
    notice: str = "",
    edit: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    store = KnowledgeStore(db)
    faqs = await store.list_faqs(q=q)
    editing = await store.get_faq(edit) if edit else None
    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
            "tab": "faqs",
            "active_nav": "knowledge",
            "faqs": faqs,
            "q": q,
            "editing": editing,
            "notice": notice,
        },
    )


@router.post("/faqs", name="dashboard_knowledge_faq_save")
async def knowledge_faq_save(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
    faq_id: str = Form(""),
    question: str = Form(...),
    answer: str = Form(...),
    category: str = Form(""),
    active: Optional[str] = Form(default=None),
):
    store = KnowledgeStore(db)
    fid = int(faq_id) if str(faq_id).strip().isdigit() else None
    row = await store.get_faq(fid) if fid else None
    if row is None:
        row = KnowledgeFaq(source="manual")
    row.question = question.strip()
    row.answer = answer.strip()
    row.category = category.strip()
    row.active = active == "on"
    await store.save_faq(row)
    invalidate_instructions_cache()
    return _redirect("faqs", "FAQ guardada")


@router.post("/faqs/{faq_id}/toggle", name="dashboard_knowledge_faq_toggle")
async def knowledge_faq_toggle(
    faq_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    store = KnowledgeStore(db)
    row = await store.get_faq(faq_id)
    if not row:
        raise HTTPException(status_code=404, detail="FAQ no encontrada")
    row.active = not row.active
    await store.save_faq(row)
    invalidate_instructions_cache()
    return _redirect("faqs", "FAQ actualizada")


@router.get("/skills", response_class=HTMLResponse, name="dashboard_knowledge_skills")
async def knowledge_skills(
    request: Request,
    notice: str = "",
    edit: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    store = KnowledgeStore(db)
    skills = await store.list_skills()
    editing = await store.get_skill(edit) if edit else None
    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
            "tab": "skills",
            "active_nav": "knowledge",
            "skills": skills,
            "editing": editing,
            "notice": notice,
        },
    )


@router.post("/skills", name="dashboard_knowledge_skill_save")
async def knowledge_skill_save(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
    skill_id: str = Form(""),
    title: str = Form(...),
    when_to_apply: str = Form(""),
    body: str = Form(""),
    active: Optional[str] = Form(default=None),
):
    store = KnowledgeStore(db)
    sid = int(skill_id) if str(skill_id).strip().isdigit() else None
    row = await store.get_skill(sid) if sid else None
    if row is None:
        row = KnowledgeSkill(source="manual")
    row.title = title.strip()
    row.when_to_apply = when_to_apply.strip()
    row.body = body.strip()
    row.active = active == "on"
    await store.save_skill(row)
    invalidate_instructions_cache()
    return _redirect("skills", "Skill guardado")


@router.post("/skills/{skill_id}/toggle", name="dashboard_knowledge_skill_toggle")
async def knowledge_skill_toggle(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    store = KnowledgeStore(db)
    row = await store.get_skill(skill_id)
    if not row:
        raise HTTPException(status_code=404, detail="Skill no encontrado")
    row.active = not row.active
    await store.save_skill(row)
    invalidate_instructions_cache()
    return _redirect("skills", "Skill actualizado")


@router.get("/files", response_class=HTMLResponse, name="dashboard_knowledge_files")
async def knowledge_files(
    request: Request,
    notice: str = "",
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    store = KnowledgeStore(db)
    files = await store.list_files()
    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
            "tab": "files",
            "active_nav": "knowledge",
            "files": files,
            "notice": notice,
        },
    )


@router.post("/files", name="dashboard_knowledge_file_upload")
async def knowledge_file_upload(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
    upload: UploadFile = File(...),
):
    name = Path(upload.filename or "archivo").name
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD:
        raise HTTPException(status_code=400, detail="Solo PDF, TXT o Markdown")
    dest_name = f"{uuid4().hex[:10]}_{name}"
    dest = uploads_dir() / dest_name
    data = await upload.read()
    dest.write_bytes(data)
    store = KnowledgeStore(db)
    row = KnowledgeFile(
        filename=name,
        stored_path=str(dest),
        mime=upload.content_type or "",
        byte_size=len(data),
        status="pending",
        active=True,
        source="manual",
    )
    await store.save_file(row)
    await ingest_file(db, row)
    invalidate_instructions_cache()
    return _redirect("files", "Archivo indexado")


@router.post("/files/{file_id}/reindex", name="dashboard_knowledge_file_reindex")
async def knowledge_file_reindex(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    store = KnowledgeStore(db)
    row = await store.get_file(file_id)
    if not row:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    await ingest_file(db, row)
    invalidate_instructions_cache()
    return _redirect("files", "Reindexado")


@router.post("/files/{file_id}/toggle", name="dashboard_knowledge_file_toggle")
async def knowledge_file_toggle(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    store = KnowledgeStore(db)
    row = await store.get_file(file_id)
    if not row:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    row.active = not row.active
    await store.save_file(row)
    invalidate_instructions_cache()
    return _redirect("files", "Archivo actualizado")


@router.post("/files/{file_id}/delete", name="dashboard_knowledge_file_delete")
async def knowledge_file_delete(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    store = KnowledgeStore(db)
    row = await store.get_file(file_id)
    if not row:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    path = Path(row.stored_path)
    await store.delete_file(row)
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
    invalidate_instructions_cache()
    return _redirect("files", "Archivo eliminado")


@router.get("/tools", response_class=HTMLResponse, name="dashboard_knowledge_tools")
async def knowledge_tools(
    request: Request,
    _: None = Depends(require_dashboard_auth),
):
    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
            "tab": "tools",
            "active_nav": "knowledge",
            "tools": REGISTERED_TOOLS,
            "notice": "",
        },
    )
