"""Instrucciones del agente GIA: políticas editables + tools fijos + business/skills."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeBusiness, KnowledgeProduct, KnowledgeSkill
from app.services.knowledge.seed import faq_question as _faq_question
from app.services.knowledge.store import KnowledgeStore
from app.services.knowledge.tools_registry import REGISTERED_TOOLS

# Editable en /dashboard/knowledge/instructions. Fallback si la DB está vacía.
DEFAULT_AGENT_INSTRUCTIONS = """
CÓMO HABLAR
- Español, breve, de usted (salvo que el cliente use tú).
- Sin emojis. Una o dos preguntas por turno; cierra con una pregunta que avance la venta.
- No inventes IDs internos ni hables como si fueras un sistema técnico.

POLÍTICAS DE NEGOCIO (prioridad alta)
1) Catálogo: solo acero al carbono de GIA (aceros planos, acanalados, tubería
   industrial negra comercial, varilla, alambre). NO vendemos acero inoxidable
   ni aluminio. Si lo piden: dilo de inmediato, NO digas que sí se puede,
   ofrece alternativa del catálogo (p. ej. galvanizada / CR / HR) y pregunta
   si les sirve. NO llames create_lead por inoxidable/aluminio.

2) Mayoreo: pedido mínimo 1 tonelada por partida y 3 toneladas en total.
   Pedidos de menudeo (piezas sueltas, “5 láminas”, “unas cuantas”, etc.)
   SIN llegar a ese mínimo: explica el mínimo, ofrece consolidar partidas o
   canalizar a distribuidor de menudeo. NO digas que “sí se puede sin problema”.
   NO llames create_lead solo por menudeo bajo mínimo.

3) create_lead solo si hay intención real SOBRE producto del catálogo Y
   volumen mayoreo (o pide explícitamente hablar con ventas/asesor humano).
   Si el caso es fuera de catálogo o bajo mínimo, responde la política y
   pregunta si quieren otra línea / consolidar; no registres lead.

4) No inventes precios finales, inventarios exactos ni CLABEs.
""".strip()

# Fijo: contrato de tools. No se edita desde el dashboard.
TOOL_RULES = """
HERRAMIENTAS (fijas en código)

- create_lead: registra un prospecto calificado en el servidor de GIA.
  Respeta las políticas de catálogo/mayoreo definidas arriba.
- escalate_to_human: pasa la conversación a un asesor humano en Chatwoot
  (status open). Úsala con create_lead (handed_off=true) cuando corresponda
  escalar un caso válido.
- search_knowledge: busca en el catálogo de productos/servicios, FAQs, skills
  y archivos indexados si el contexto del turno no alcanza. No inventes lo
  que no aparezca ahí.
- send_catalog: envía el PDF de la Carta de Presentación GIA (líneas y
  perfiles). Úsala cuando pidan catálogo, carta de presentación, brochure o
  el documento de productos. NO la uses para la lista de precios mensual
  (esa la envía el asesor) ni para la presentación corporativa 2027.
  Tras enviarla, confirma en texto y pregunta material/tonelaje.

MENSAJES WHATSAPP
- Tú decides cuántas burbujas enviar, como un asesor en WhatsApp.
- Por defecto UN solo mensaje si es la misma idea (varias oraciones juntas).
- Parte en 2–3 burbujas SOLO cuando un humano mandaría otro mensaje aparte:
  saludo y luego el tema; un dato y luego una pregunta distinta; un no/política
  y luego la alternativa; confirmar que pasa con un asesor.
- NUNCA separes oraciones del mismo pensamiento. No partes por partir.
- Si partes, usa una línea que solo tenga --- entre burbujas. Máximo 4.
""".strip()

_instructions_version = 0
_instructions_cache: Optional[Tuple[int, str]] = None


def invalidate_instructions_cache() -> None:
    global _instructions_version, _instructions_cache
    _instructions_version += 1
    _instructions_cache = None


def _format_faqs(faqs: List[Dict[str, Any]], char_limit: int) -> str:
    lines: List[str] = []
    total = 0
    for item in faqs:
        answer = (item.get("answer") or "").strip()
        q = _faq_question(item)
        block = f"P: {q}\nR: {answer}"
        if total + len(block) + 2 > char_limit:
            lines.append("… (FAQs truncadas por límite de contexto)")
            break
        lines.append(block)
        total += len(block) + 2
    return "\n\n".join(lines)


def _format_business_row(row: KnowledgeBusiness) -> str:
    parts = [
        f"Descripción: {row.business_description or ''}",
        f"Compra: {row.purchase_info or ''}",
        f"Pagos: {row.payment_method or ''}",
        f"Entrega: {row.delivery_and_shipping or ''}",
        f"Devoluciones: {row.return_policy or ''}",
        f"Email: {row.email or ''}",
        f"Horario: {row.hours_of_operation or ''}",
        f"Dirección: {row.address or ''}",
    ]
    return "\n".join(p for p in parts if not p.endswith(": "))


PRODUCT_KIND_LABELS = {
    "product": "Producto",
    "service": "Servicio",
    "out_of_catalog": "No se ofrece",
}

PRODUCT_CATEGORY_LABELS = {
    "aceros_planos": "Aceros planos",
    "acanalados": "Lámina acanalada",
    "tuberia": "Tubería industrial",
    "varilla": "Varilla",
    "alambre": "Alambre",
    "servicios": "Servicios de transformación",
    "limites": "Fuera de catálogo",
}


def _format_catalog(products: List[KnowledgeProduct]) -> str:
    active = [p for p in products if p.active]
    if not active:
        return ""
    groups: Dict[str, List[KnowledgeProduct]] = {}
    order: List[str] = []
    for p in active:
        key = (p.category or "otros").strip() or "otros"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(p)

    blocks = [
        "Usa esta lista como fuente de verdad de lo que GIA vende hoy. "
        "No afirmes líneas que no estén aquí. Si el cliente pide algo marcado "
        "como NO SE OFRECE, dilo de inmediato y ofrece una alternativa del catálogo."
    ]
    for cat in order:
        heading = PRODUCT_CATEGORY_LABELS.get(cat, cat.replace("_", " ").capitalize())
        lines = [heading]
        for p in groups[cat]:
            summary = (p.summary or "").strip()
            details = (p.details or "").strip()
            marker = ""
            if p.kind == "out_of_catalog":
                marker = " [NO SE OFRECE]"
            elif p.kind == "service":
                marker = " [servicio]"
            line = f"- {p.name}{marker}"
            if summary:
                line += f": {summary}"
            lines.append(line)
            if details:
                lines.append(f"  {details}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _format_skills_index(skills: List[KnowledgeSkill]) -> str:
    blocks = []
    for s in skills:
        if not s.active:
            continue
        when = (s.when_to_apply or "").strip()
        line = f"- {s.title}"
        if when:
            line += f": {when}"
        blocks.append(line)
    return "\n".join(blocks)


def resolve_agent_instructions(row: Optional[KnowledgeBusiness]) -> str:
    """Texto editable (dashboard) o default de código si aún está vacío."""
    if row is not None:
        stored = (getattr(row, "agent_instructions", None) or "").strip()
        if stored:
            return stored
    return DEFAULT_AGENT_INSTRUCTIONS


async def build_agent_instructions(db: AsyncSession) -> str:
    """System prompt: instrucciones editables + negocio/skills + tools fijos."""
    global _instructions_cache
    if _instructions_cache and _instructions_cache[0] == _instructions_version:
        return _instructions_cache[1]

    store = KnowledgeStore(db)
    business_row = await store.get_business()
    editable = resolve_agent_instructions(business_row)
    business = _format_business_row(business_row) if business_row else ""
    skills = await store.list_skills(include_inactive=False)
    skills_index = _format_skills_index(skills)
    products = await store.list_products(include_inactive=False)
    catalog = _format_catalog(products)
    tools_list = "\n".join(f"- {t['name']}: {t['when']}" for t in REGISTERED_TOOLS)

    sections = [
        editable,
        "INFORMACIÓN DE NEGOCIO\n\n" + business if business else "",
        "CATÁLOGO Y SERVICIOS\n\n" + catalog if catalog else "",
        "SKILLS (índice; detalle vía retrieval / search_knowledge)\n\n" + skills_index
        if skills_index
        else "",
        TOOL_RULES + ("\n\n" + tools_list if tools_list else ""),
    ]
    text = "\n\n---\n\n".join(s for s in sections if s)
    _instructions_cache = (_instructions_version, text)
    return text
