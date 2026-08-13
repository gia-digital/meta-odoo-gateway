"""Carga instrucciones del agente GIA desde docs/ + agent_info/."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from app.core.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
AGENT_INFO = ROOT / "agent_info"
DOCS = ROOT / "docs"


def _extract_prompt_block(md: str) -> str:
    """Extrae el primer bloque ``` ... ``` de agent_prompt.md."""
    match = re.search(r"```\n(.*?)```", md, re.DOTALL)
    if match:
        return match.group(1).strip()
    return md.strip()


def _faq_question(item: Dict[str, Any]) -> str:
    """Soporta schema Meta (`question`) y listas (`questions`)."""
    q = item.get("question")
    if isinstance(q, str) and q.strip():
        return q.strip()
    questions = item.get("questions") or []
    if questions:
        return str(questions[0]).strip()
    return "(sin pregunta)"


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


def _format_business_info(payload: Dict[str, Any]) -> str:
    contact = payload.get("contact_info") or {}
    parts = [
        f"Descripción: {payload.get('business_description', '')}",
        f"Compra: {payload.get('purchase_info', '')}",
        f"Pagos: {payload.get('payment_method', '')}",
        f"Entrega: {payload.get('delivery_and_shipping', '')}",
        f"Devoluciones: {payload.get('return_policy', '')}",
        f"Email: {contact.get('email', '')}",
        f"Horario: {contact.get('hours_of_operation', '')}",
        f"Dirección: {contact.get('address', '')}",
    ]
    return "\n".join(p for p in parts if p and not p.endswith(": "))


def _format_skills(skills: List[Dict[str, Any]]) -> str:
    blocks = []
    for s in skills:
        title = s.get("title", "skill")
        when = s.get("description", "")
        body = s.get("skill", "")
        blocks.append(f"### {title}\nCuando aplicar: {when}\n\n{body}")
    return "\n\n".join(blocks)


@lru_cache
def build_agent_instructions() -> str:
    """System instructions cacheadas (reiniciar app si cambia agent_info)."""
    settings = get_settings()

    prompt_path = DOCS / "agent_prompt.md"
    base = ""
    if prompt_path.exists():
        base = _extract_prompt_block(prompt_path.read_text(encoding="utf-8"))

    business = ""
    bi_path = AGENT_INFO / "business_info.json"
    if bi_path.exists():
        bi = json.loads(bi_path.read_text(encoding="utf-8"))
        business = _format_business_info(bi.get("payload") or bi)

    skills_text = ""
    skills_path = AGENT_INFO / "skills.json"
    if skills_path.exists():
        data = json.loads(skills_path.read_text(encoding="utf-8"))
        skills_text = _format_skills(data.get("skills") or [])

    faqs_text = ""
    faqs_path = AGENT_INFO / "faqs.json"
    if faqs_path.exists():
        data = json.loads(faqs_path.read_text(encoding="utf-8"))
        faqs_text = _format_faqs(
            data.get("faqs") or [], settings.agent_faq_char_limit
        )

    hard_rules = """
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

    tools_note = """
HERRAMIENTAS

- create_lead: registra un prospecto calificado en el servidor de GIA.
  Úsala solo si el material es de catálogo y hay mayoreo (o pidió hablar
  con ventas). NUNCA por inoxidable/aluminio ni por menudeo bajo mínimo.
- escalate_to_human: pasa la conversación a un asesor humano en Chatwoot
  (status open). Úsala con create_lead (handed_off=true) cuando corresponda
  escalar un caso válido.

Responde siempre en español, breve, de usted salvo que el cliente use tú.
No digas IDs internos al cliente.
""".strip()

    sections = [
        hard_rules,
        base,
        "INFORMACIÓN DE NEGOCIO\n\n" + business if business else "",
        "SKILLS OPERATIVOS\n\n" + skills_text if skills_text else "",
        "FAQS DE REFERENCIA\n\n" + faqs_text if faqs_text else "",
        tools_note,
    ]
    return "\n\n---\n\n".join(s for s in sections if s)
