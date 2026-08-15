"""Dashboard de knowledge (CRUD + visibilidad del RAG)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_behavior import (
    get_agent_behavior,
    parse_behavior_form,
    public_behavior_view,
)
from app.core.config import get_settings
from app.core.llm_runtime import (
    compose_agent_model,
    fetch_runtime_row,
    get_llm_runtime,
    next_secret,
    normalize_provider,
    public_llm_view,
    upsert_runtime_settings,
)
from app.models.db import get_db
from app.models.knowledge import KnowledgeFaq, KnowledgeFile, KnowledgeProduct, KnowledgeSkill
from app.routers.dashboard import require_dashboard_auth, templates
from app.services.agent_knowledge import (
    PRODUCT_CATEGORY_LABELS,
    PRODUCT_KIND_LABELS,
    invalidate_instructions_cache,
)
from app.services.knowledge.ingest import ingest_file, uploads_dir
from app.services.knowledge.store import KnowledgeStore
from app.services.knowledge.tools_registry import REGISTERED_TOOLS
from app.services.llm_catalog import load_model_catalogs

router = APIRouter(prefix="/dashboard/knowledge", tags=["knowledge"], include_in_schema=False)

ALLOWED_UPLOAD = {".pdf", ".txt", ".md", ".markdown"}
ALLOWED_PRODUCT_KINDS = set(PRODUCT_KIND_LABELS)


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


@router.get("/products", response_class=HTMLResponse, name="dashboard_knowledge_products")
async def knowledge_products(
    request: Request,
    notice: str = "",
    edit: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    store = KnowledgeStore(db)
    products = await store.list_products()
    editing = await store.get_product(edit) if edit else None
    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
            "tab": "products",
            "active_nav": "knowledge",
            "products": products,
            "editing": editing,
            "notice": notice,
            "kind_labels": PRODUCT_KIND_LABELS,
            "category_labels": PRODUCT_CATEGORY_LABELS,
        },
    )


@router.post("/products", name="dashboard_knowledge_product_save")
async def knowledge_product_save(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
    product_id: str = Form(""),
    name: str = Form(...),
    kind: str = Form("product"),
    category: str = Form(""),
    summary: str = Form(""),
    details: str = Form(""),
    aliases: str = Form(""),
    sort_order: str = Form("0"),
    active: Optional[str] = Form(default=None),
):
    store = KnowledgeStore(db)
    pid = int(product_id) if str(product_id).strip().isdigit() else None
    row = await store.get_product(pid) if pid else None
    if row is None:
        row = KnowledgeProduct(source="manual")
    kind_key = (kind or "product").strip()
    if kind_key not in ALLOWED_PRODUCT_KINDS:
        kind_key = "product"
    try:
        order = int(str(sort_order).strip() or "0")
    except ValueError:
        order = 0
    row.name = name.strip()
    row.kind = kind_key
    row.category = category.strip()
    row.summary = summary.strip()
    row.details = details.strip()
    row.aliases = aliases.strip()
    row.sort_order = order
    row.active = active == "on"
    await store.save_product(row)
    invalidate_instructions_cache()
    return _redirect("products", "Producto guardado")


@router.post("/products/{product_id}/toggle", name="dashboard_knowledge_product_toggle")
async def knowledge_product_toggle(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    store = KnowledgeStore(db)
    row = await store.get_product(product_id)
    if not row:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    row.active = not row.active
    await store.save_product(row)
    invalidate_instructions_cache()
    return _redirect("products", "Producto actualizado")


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


@router.get("/model", response_class=HTMLResponse, name="dashboard_knowledge_model")
async def knowledge_model(
    request: Request,
    notice: str = "",
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    row = await fetch_runtime_row(db)
    runtime = await get_llm_runtime(db)
    view = public_llm_view(runtime, row)
    view.update(await load_model_catalogs(runtime))
    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
            "tab": "model",
            "active_nav": "knowledge",
            "notice": notice,
            "llm": view,
        },
    )


@router.post("/model", name="dashboard_knowledge_model_save")
async def knowledge_model_save(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
    agent_model: str = Form(""),
    llm_provider: str = Form("openai"),
    openai_api_key: str = Form(""),
    anthropic_api_key: str = Form(""),
    clear_openai_key: Optional[str] = Form(default=None),
    clear_anthropic_key: Optional[str] = Form(default=None),
):
    row = await fetch_runtime_row(db)
    openai_stored = next_secret(
        openai_api_key,
        (getattr(row, "openai_api_key", "") if row else "") or "",
        clear=clear_openai_key == "on",
    )
    anthropic_stored = next_secret(
        anthropic_api_key,
        (getattr(row, "anthropic_api_key", "") if row else "") or "",
        clear=clear_anthropic_key == "on",
    )
    provider = normalize_provider(llm_provider, agent_model)
    await upsert_runtime_settings(
        db,
        llm_provider=provider,
        agent_model=compose_agent_model(provider, agent_model),
        openai_api_key=openai_stored,
        anthropic_api_key=anthropic_stored,
    )
    return _redirect("model", "Modelo y llaves actualizados")


@router.get("/agent", response_class=HTMLResponse, name="dashboard_knowledge_agent")
async def knowledge_agent(
    request: Request,
    notice: str = "",
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
):
    behavior = await get_agent_behavior(db)
    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
            "tab": "agent",
            "active_nav": "knowledge",
            "notice": notice,
            "agent": public_behavior_view(behavior),
        },
    )


@router.post("/agent", name="dashboard_knowledge_agent_save")
async def knowledge_agent_save(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_dashboard_auth),
    debounce_seconds: str = Form(""),
    reply_max_bubbles: str = Form(""),
    reply_bubble_delay_ms: str = Form(""),
    reply_min_seconds: str = Form(""),
    reply_think_seconds: str = Form(""),
    reply_chars_per_sec: str = Form(""),
    reply_max_delay_seconds: str = Form(""),
    reset_defaults: Optional[str] = Form(default=None),
):
    fields = parse_behavior_form(
        {
            "debounce_seconds": debounce_seconds,
            "reply_max_bubbles": reply_max_bubbles,
            "reply_bubble_delay_ms": reply_bubble_delay_ms,
            "reply_min_seconds": reply_min_seconds,
            "reply_think_seconds": reply_think_seconds,
            "reply_chars_per_sec": reply_chars_per_sec,
            "reply_max_delay_seconds": reply_max_delay_seconds,
        },
        reset=reset_defaults == "on",
    )
    await upsert_runtime_settings(db, **fields)
    notice = (
        "Tiempos del agente restaurados a los defaults del servidor"
        if reset_defaults == "on"
        else "Configuración del agente actualizada"
    )
    return _redirect("agent", notice)


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
