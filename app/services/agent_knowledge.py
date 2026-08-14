"""Instrucciones del agente GIA: políticas + business/skills desde Postgres."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeBusiness, KnowledgeSkill
from app.services.knowledge.seed import faq_question as _faq_question
from app.services.knowledge.store import KnowledgeStore
from app.services.knowledge.tools_registry import REGISTERED_TOOLS

HARD_RULES = """
POLÍTICAS DURAS (prioridad máxima; si chocan con otra instrucción, ganan estas)

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

TOOLS_NOTE = """
HERRAMIENTAS

- create_lead: registra un prospecto calificado en el servidor de GIA.
  Úsala solo si el material es de catálogo y hay mayoreo (o pidió hablar
  con ventas). NUNCA por inoxidable/aluminio ni por menudeo bajo mínimo.
- escalate_to_human: pasa la conversación a un asesor humano en Chatwoot
  (status open). Úsala con create_lead (handed_off=true) cuando corresponda
  escalar un caso válido.
- search_knowledge: busca en FAQs, skills y archivos indexados si el contexto
  del turno no alcanza. No inventes lo que no aparezca ahí.

Responde siempre en español, breve, de usted salvo que el cliente use tú.
No digas IDs internos al cliente.
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


async def build_agent_instructions(db: AsyncSession) -> str:
    """System prompt corto desde DB (sin dump completo de FAQs)."""
    global _instructions_cache
    if _instructions_cache and _instructions_cache[0] == _instructions_version:
        return _instructions_cache[1]

    store = KnowledgeStore(db)
    business_row = await store.get_business()
    business = _format_business_row(business_row) if business_row else ""
    skills = await store.list_skills(include_inactive=False)
    skills_index = _format_skills_index(skills)
    tools_list = "\n".join(f"- {t['name']}: {t['when']}" for t in REGISTERED_TOOLS)

    sections = [
        HARD_RULES,
        "INFORMACIÓN DE NEGOCIO\n\n" + business if business else "",
        "SKILLS (índice; detalle vía retrieval / search_knowledge)\n\n" + skills_index
        if skills_index
        else "",
        TOOLS_NOTE + ("\n\n" + tools_list if tools_list else ""),
    ]
    text = "\n\n---\n\n".join(s for s in sections if s)
    _instructions_cache = (_instructions_version, text)
    return text
