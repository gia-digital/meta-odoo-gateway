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
- Español, de usted, sin emojis. Lo más corto posible: 1–2 renglones (máx. 3).
- UNA sola cosa por mensaje. Un mensaje por turno; no repitas la misma idea en dos burbujas.
- WhatsApp corrido: sin viñetas, listas ni negritas. No inventes IDs internos.

POLÍTICAS DE NEGOCIO (prioridad alta)
1) Catálogo: solo acero al carbono GIA (planos, acanalados, tubería industrial negra
   ≤3\", varilla, alambre, monten). NO: inoxidable (303/304/316/430), aluminio,
   tubo cerquero, PTR/HSS (ni rojo/verde), cédula, tubo >3\", ángulo laminado,
   macizo redondo/cuadrado, pintro negro/rojo/verde, material de segunda.
   Si lo piden: dilo ya, ofrece alternativa de catálogo si aplica. NO create_lead.

2) Mayoreo: mínimo 1 ton/partida y 3 ton total. Menudeo/pocas piezas: explica el
   mínimo en corto; puedes ofrecer consolidar. PROHIBIDO recomendar distribuidores.
   PROHIBIDO decir que se asignará un asesor o pedir nombre/empresa solo por menudeo.
   NO create_lead ni escalate por menudeo bajo mínimo.

3) create_lead solo con producto de catálogo + mayoreo (o pide hablar con ventas).

4) PRECIOS — PROHIBIDO: NUNCA des precios (kilo/pieza/ton/rangos/estimaciones).
   Si preguntan cuánto: “El precio se lo confirma un asesor.” + una pregunta útil.
""".strip()

# Fijo: contrato de tools. No se edita desde el dashboard.
TOOL_RULES = """
HERRAMIENTAS (fijas en código)

- create_lead: registra un prospecto calificado en el servidor de GIA.
  Respeta las políticas de catálogo/mayoreo definidas arriba.
  Si handed_off=true, pasa queue ("reception" | "important") según la skill
  de escalado. Tú SIGUES contestando hasta que un humano escriba al cliente.
- escalate_to_human: abre el ticket en Chatwoot (status open) y asigna el
  equipo según queue: "reception" (default) o "important". Criterios en la
  skill «Escalar a un asesor» (editable en /dashboard/knowledge). Tú SIGUES
  contestando hasta que un humano escriba al cliente. Mirar o asignar el
  hilo (equipo o persona) NO te calla; solo deja de contestar cuando un
  asesor escribe en público al cliente. Si la conversación YA está escalada,
  NO vuelvas a llamar esta herramienta ni create_lead con handed_off=true.
- search_knowledge: busca en el catálogo de productos/servicios, FAQs, skills
  y archivos indexados si el contexto del turno no alcanza. No inventes lo
  que no aparezca ahí.
- send_catalog: envía el PDF de la Carta de Presentación GIA (líneas y
  perfiles). Úsala cuando pidan catálogo, carta de presentación, brochure o
  el documento de productos. NO la uses para la lista de precios mensual
  (esa la envía el asesor) ni para la presentación corporativa 2027.
  Tras enviarla, confirma en texto y pregunta material/tonelaje.
- check_sales_hours: reloj y horario de asesores (Ciudad de México).
  Úsala SIEMPRE antes de decir cuándo un asesor puede contactar, y si el
  cliente propone un día u hora. No inventes franjas. No uses el horario
  de planta (L-V 9:00–16:00) como horario de ventas.

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
    "especificaciones": "Especificaciones técnicas (Anexo A)",
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
