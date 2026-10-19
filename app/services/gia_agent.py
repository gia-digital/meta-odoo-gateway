"""
Agente conversacional GIA vía OpenAI Agents SDK.

- OpenAI → Responses API nativa (OpenAIResponsesModel). Preferido para gpt-5.*.
- Anthropic u otros → LiteLLM (chat completions del proveedor).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.business_hours import (
    check_proposed_slot,
    client_handoff_guidance,
    hours_prompt_block,
)
from app.core.config import get_settings
from app.core.llm_runtime import LlmRuntime, get_llm_runtime
from app.core.logging import get_logger
from app.models.conversation import (
    Channel,
    Conversation,
    ConversationStatus,
    QualificationSource,
)
from app.services.agent_knowledge import build_agent_instructions
from app.services.catalog_document import deliver_catalog, find_catalog_pdf
from app.services.chatwoot_client import ChatwootClient, resolve_handoff_queue
from app.services.conversation import ConversationService
from app.services.knowledge.retriever import format_hits, retrieve_knowledge

logger = get_logger(__name__)

_EMPTY_REPLY_FALLBACK = (
    "Gracias por su mensaje. Un momento, por favor; "
    "si prefiere, puedo canalizarle con un asesor de GIA."
)
_HANDED_OFF_REPLY_FALLBACK = (
    "Perfecto, ya quedó registrado. Un asesor de GIA le dará seguimiento "
    "por este chat en horario laboral."
)


def _conversation_handed_off(conversation: Conversation) -> bool:
    if conversation.status == ConversationStatus.handed_off:
        return True
    return getattr(conversation, "handed_off_at", None) is not None


def _empty_reply_fallback(*, handed_off: bool) -> str:
    if handed_off:
        return _HANDED_OFF_REPLY_FALLBACK
    return _EMPTY_REPLY_FALLBACK


def _handoff_note_lead(
    *, already_handed_off: bool, team_label: str, reason: str, summary: str
) -> str:
    prefix = "Re-escalado" if already_handed_off else "Lead creado y escalado"
    return f"{prefix} → {team_label}. Motivo: {reason}. {summary}".strip()


def _rehandoff_tool_hint() -> str:
    return (
        "Si el cliente solo confirma o vuelve a pedir asesor, responde UNA línea "
        "breve; no repitas el mismo discurso de escalado en cada turno."
    )


def _lead_tool_reply(
    *,
    conv_id: Any,
    status: str,
    handed_off: bool,
    already_handed_off: bool,
) -> str:
    if handed_off:
        action = "actualizado y re-asignado" if already_handed_off else "registrado"
        return (
            f"Lead {action} (id interno {conv_id}, status={status}). "
            f"{client_handoff_guidance()} No menciones IDs internos ni el equipo. "
            f"{_rehandoff_tool_hint()}"
        )
    return (
        f"Lead registrado (id interno {conv_id}, status={status}). "
        f"{client_handoff_guidance()} No menciones IDs internos. "
        "Si aún no llamaste check_sales_hours, úsala antes de hablar de horarios."
    )


def _escalate_tool_reply() -> str:
    return (
        f"{client_handoff_guidance()} "
        "No menciones el equipo interno al cliente. "
        f"{_rehandoff_tool_hint()}"
    )


def record_playground_event(
    bot: BotContext, kind: str, label: str, detail: str = ""
) -> None:
    events = bot.extra.setdefault("playground_events", [])
    events.append(
        {
            "kind": kind,
            "label": label,
            "detail": (detail or "").strip()[:500],
        }
    )


def _clip_field(value: str, limit: int) -> str:
    return (value or "").strip()[:limit]


def sandbox_register_lead(
    bot: BotContext,
    *,
    reason: str,
    summary: str,
    product_interest: str = "",
    budget: str = "",
    timeline: str = "",
    preferred_contact_time: str = "",
    user_name: str = "",
    user_phone: str = "",
    user_email: str = "",
    handed_off: bool = False,
    queue: str = "reception",
) -> str:
    """Simula create_lead: actualiza el hilo en memoria, sin DB ni Chatwoot."""
    conv = bot.conversation
    already_handed_off = _conversation_handed_off(conv)
    if user_name.strip():
        conv.user_name = _clip_field(user_name, 255)
        bot.user_name = conv.user_name
    if user_phone.strip():
        conv.user_phone = _clip_field(user_phone, 64)
        bot.user_phone = conv.user_phone
    if user_email.strip():
        conv.user_email = _clip_field(user_email, 255)
        bot.user_email = conv.user_email
    if product_interest.strip():
        conv.product_interest = _clip_field(product_interest, 255)
    if summary.strip():
        conv.lead_summary = _clip_field(summary, 4000)
    if budget.strip():
        conv.budget = _clip_field(budget, 255)
    if timeline.strip():
        conv.timeline = _clip_field(timeline, 255)
    if preferred_contact_time.strip():
        conv.preferred_contact_time = _clip_field(preferred_contact_time, 255)
    conv.qualification_source = QualificationSource.chatwoot_agent
    conv.qualification_reason = _clip_field(
        reason or summary or "Qualified by Chatwoot Agent Bot", 4000
    )
    now = datetime.now(timezone.utc)
    if getattr(conv, "qualified_at", None) is None:
        conv.qualified_at = now
    if handed_off:
        conv.status = ConversationStatus.handed_off
        if getattr(conv, "handed_off_at", None) is None:
            conv.handed_off_at = now
        bot.handed_off = True
    elif conv.status == ConversationStatus.active:
        conv.status = ConversationStatus.qualified

    _, team_label = resolve_handoff_queue(queue)
    if handed_off and already_handed_off:
        label = "Reasignaría el prospecto"
    elif handed_off:
        label = "Registraría y escalaría el prospecto"
    else:
        label = "Registraría un prospecto"
    detail_bits = [
        bit.strip()
        for bit in (product_interest, budget, timeline, summary, reason)
        if (bit or "").strip()
    ]
    if handed_off:
        detail_bits.append(f"cola: {team_label}")
    record_playground_event(bot, "lead", label, " · ".join(detail_bits))
    logger.info(
        "playground_tool_create_lead",
        handed_off=handed_off,
        queue=(queue or "reception") if handed_off else None,
        re_handoff=handed_off and already_handed_off,
    )
    return _lead_tool_reply(
        conv_id=conv.id,
        status=conv.status.value,
        handed_off=handed_off,
        already_handed_off=already_handed_off,
    )


def sandbox_escalate(bot: BotContext, *, reason: str, queue: str = "reception") -> str:
    """Simula escalate_to_human sin abrir ticket ni escribir en la base."""
    conv = bot.conversation
    already_handed_off = _conversation_handed_off(conv) or bot.handed_off
    now = datetime.now(timezone.utc)
    conv.status = ConversationStatus.handed_off
    if getattr(conv, "handed_off_at", None) is None:
        conv.handed_off_at = now
    if (reason or "").strip():
        conv.qualification_reason = _clip_field(reason, 4000)
    bot.handed_off = True
    _, team_label = resolve_handoff_queue(queue)
    label = "Re-escalaría a un asesor" if already_handed_off else "Escalaría a un asesor"
    record_playground_event(
        bot,
        "handoff",
        label,
        f"{team_label}. {(reason or '').strip()}".strip(" ."),
    )
    logger.info(
        "playground_tool_escalate",
        reason=reason,
        queue=queue or "reception",
        team_label=team_label,
        re_handoff=already_handed_off,
    )
    return _escalate_tool_reply()


async def sandbox_send_catalog(bot: BotContext) -> str:
    """Simula el PDF del catálogo: no lo sube a Chatwoot."""
    if bot.extra.get("catalog_sent"):
        return (
            "El catálogo ya se envió en este turno. Confirma al cliente que lo "
            "tiene y pregunta qué material y tonelaje busca."
        )
    path = await find_catalog_pdf(bot.db)
    if path is None:
        record_playground_event(
            bot,
            "catalog",
            "No encontró la carta de presentación",
            "El agente describirá las líneas en texto.",
        )
        return (
            "No se encontró el PDF de la carta de presentación. Describe las "
            "líneas del catálogo en texto (aceros planos, acanalados, tubería "
            "industrial, varilla y alambre) y ofrece que un asesor lo envíe."
        )
    bot.extra["catalog_sent"] = True
    record_playground_event(
        bot,
        "catalog",
        "Enviaría la carta de presentación",
        path.name,
    )
    logger.info("playground_tool_send_catalog", path=str(path))
    return (
        "Catálogo enviado (Carta de presentación GIA.pdf). Confirma al cliente "
        "que ya lo tiene y pregunta qué material y tonelaje busca. No lo "
        "vuelvas a enviar en este turno. No es la lista de precios mensual."
    )


@dataclass
class BotContext:
    """Contexto por request para tools del agente."""

    db: AsyncSession
    conversation: Conversation
    channel: Channel
    external_user_id: str
    chatwoot_conversation_id: int
    user_name: Optional[str] = None
    user_phone: Optional[str] = None
    user_email: Optional[str] = None
    handed_off: bool = False
    fresh_cycle: bool = False
    sandbox: bool = False
    extra: dict = field(default_factory=dict)


FRESH_CYCLE_INSTRUCTION = (
    "CICLO NUEVO: Este cliente ya tuvo un pedido anterior, cerrado en Chatwoot. "
    "No retomes material, toneladas ni acuerdos de ese ciclo. "
    "Si dice que quiere lo mismo que la vez pasada, pide de nuevo producto y cantidad. "
    "Trata este mensaje como el inicio de un pedido nuevo."
)


def _resolve_api_key(model: str, runtime: Optional[LlmRuntime] = None) -> Optional[str]:
    openai_key = (runtime.openai_api_key if runtime else get_settings().openai_api_key) or ""
    anthropic_key = (
        runtime.anthropic_api_key if runtime else get_settings().anthropic_api_key
    ) or ""
    m = model.lower()
    if m.startswith("anthropic/") or "claude" in m:
        return anthropic_key.strip() or None
    if m.startswith("openai/") or m.startswith("gpt-"):
        return openai_key.strip() or None
    return anthropic_key.strip() or openai_key.strip() or None


def _parse_model(model_name: str) -> Tuple[str, str]:
    """
    Returns (transport, model_id).

    transport:
      - openai_responses → OpenAI Responses API
      - litellm → LiteLLM (Anthropic y otros)
    """
    raw = (model_name or "").strip()
    lower = raw.lower()
    if lower.startswith("openai/"):
        return "openai_responses", raw.split("/", 1)[1]
    if lower.startswith("anthropic/"):
        return "litellm", raw
    if lower.startswith("gpt-") or "luna" in lower or "sol" in lower:
        return "openai_responses", raw
    if "claude" in lower:
        return "litellm", raw if "/" in raw else f"anthropic/{raw}"
    if "/" in raw:
        return "litellm", raw
    # Nombre bare sin prefijo: asumir OpenAI Responses
    return "openai_responses", raw


def history_to_input(messages: List[Any]) -> str:
    """Convierte mensajes ORM o pares role/content a un prompt de turno."""
    lines: List[str] = []
    for m in messages:
        if hasattr(m, "direction"):
            role = "Cliente" if m.direction.value == "inbound" else "Asistente"
            body = m.body or ""
        elif isinstance(m, dict):
            role = "Cliente" if m.get("role") == "user" else "Asistente"
            body = m.get("content") or ""
        else:
            continue
        if body.strip():
            lines.append(f"{role}: {body.strip()}")
    return "\n".join(lines)


def _build_tools():
    from agents import RunContextWrapper, function_tool

    # Con `from __future__ import annotations`, get_type_hints resuelve contra
    # globals del módulo (no el import local de esta función).
    globals()["RunContextWrapper"] = RunContextWrapper

    @function_tool
    async def create_lead(
        ctx: RunContextWrapper[BotContext],
        reason: str,
        summary: str,
        product_interest: str = "",
        budget: str = "",
        timeline: str = "",
        preferred_contact_time: str = "",
        user_name: str = "",
        user_phone: str = "",
        user_email: str = "",
        handed_off: bool = False,
        queue: str = "reception",
    ) -> str:
        """
        Registra un prospecto calificado en el servidor de GIA para que ventas dé seguimiento.
        Usa SOLO si el material es del catálogo GIA (acero al carbono) y hay mayoreo
        (mín. ~1 ton/partida y 3 ton total) o el cliente pidió hablar con un asesor.
        NO uses para inoxidable, aluminio, ni pedidos de menudeo/pocas láminas bajo mínimo.
        Si handed_off=true, queue elige el equipo Chatwoot: "reception" (default) o
        "important" (prospectos de alto valor). Criterios en la skill de escalado.
        Tú sigues contestando tras escalar hasta que un humano escriba al cliente.
        """
        bot = ctx.context
        if bot.sandbox:
            return sandbox_register_lead(
                bot,
                reason=reason,
                summary=summary,
                product_interest=product_interest,
                budget=budget,
                timeline=timeline,
                preferred_contact_time=preferred_contact_time,
                user_name=user_name,
                user_phone=user_phone,
                user_email=user_email,
                handed_off=handed_off,
                queue=queue,
            )
        service = ConversationService(bot.db)
        already_handed_off = _conversation_handed_off(bot.conversation)
        conv = await service.create_lead_from_payload(
            channel=bot.channel,
            external_user_id=bot.external_user_id,
            user_name=user_name or bot.user_name,
            user_phone=user_phone or bot.user_phone or bot.external_user_id,
            user_email=user_email or bot.user_email,
            reason=reason,
            summary=summary,
            product_interest=product_interest or None,
            budget=budget or None,
            timeline=timeline or None,
            preferred_contact_time=preferred_contact_time or None,
            handed_off=handed_off,
            qualification_source=QualificationSource.chatwoot_agent,
        )
        bot.conversation = conv
        if handed_off:
            bot.handed_off = True
            team_id, team_label = resolve_handoff_queue(queue)
            try:
                async with ChatwootClient() as cw:
                    await cw.handoff_to_human(
                        bot.chatwoot_conversation_id,
                        team_id=team_id,
                        note=_handoff_note_lead(
                            already_handed_off=already_handed_off,
                            team_label=team_label,
                            reason=reason,
                            summary=summary,
                        ),
                    )
            except Exception as exc:
                logger.error(
                    "agent_create_lead_handoff_failed",
                    error=str(exc),
                    chatwoot_conversation_id=bot.chatwoot_conversation_id,
                    queue=queue,
                    team_id=team_id,
                )
        logger.info(
            "agent_tool_create_lead",
            conversation_id=conv.id,
            handed_off=handed_off,
            queue=(queue or "reception") if handed_off else None,
            re_handoff=handed_off and already_handed_off,
        )
        return _lead_tool_reply(
            conv_id=conv.id,
            status=conv.status.value,
            handed_off=handed_off,
            already_handed_off=already_handed_off,
        )

    @function_tool
    async def escalate_to_human(
        ctx: RunContextWrapper[BotContext],
        reason: str,
        queue: str = "reception",
    ) -> str:
        """
        Escala la conversación a un asesor humano en Chatwoot (abre el ticket y
        asigna equipo). Tú SIGUES contestando hasta que un humano escriba al
        cliente; asignar equipo no te calla.
        queue: "reception" (default, la mayoría) o "important" (alto valor).
        Criterios de cuándo usar cada una: skill «Escalar a un asesor».
        Usa cuando hace falta cotización formal, datos bancarios, reclamación,
        cliente con vendedor, o el cliente pide hablar con una persona.
        """
        bot = ctx.context
        if bot.sandbox:
            return sandbox_escalate(bot, reason=reason, queue=queue)
        already_handed_off = _conversation_handed_off(bot.conversation) or bot.handed_off
        service = ConversationService(bot.db)
        await service.mark_handed_off(bot.conversation, reason=reason)
        bot.handed_off = True
        team_id, team_label = resolve_handoff_queue(queue)
        note_prefix = "Re-escalado" if already_handed_off else "Escalado"
        try:
            async with ChatwootClient() as cw:
                await cw.handoff_to_human(
                    bot.chatwoot_conversation_id,
                    team_id=team_id,
                    note=f"{note_prefix} → {team_label}. Motivo: {reason}",
                )
        except Exception as exc:
            logger.error(
                "agent_escalate_chatwoot_failed",
                error=str(exc),
                chatwoot_conversation_id=bot.chatwoot_conversation_id,
                queue=queue,
                team_id=team_id,
            )
            return (
                f"Conversación marcada como escalada en el gateway, pero Chatwoot "
                f"falló al abrir el ticket: {exc}. {client_handoff_guidance()}"
            )
        logger.info(
            "agent_tool_escalate",
            conversation_id=bot.conversation.id,
            reason=reason,
            queue=queue or "reception",
            team_id=team_id,
            team_label=team_label,
            re_handoff=already_handed_off,
        )
        return _escalate_tool_reply()

    @function_tool
    async def search_knowledge(
        ctx: RunContextWrapper[BotContext],
        query: str,
    ) -> str:
        """
        Busca en el knowledge store (catálogo de productos/servicios, FAQs,
        skills, archivos) con RAG/pgvector.
        Usa si el cliente pregunta por un material, perfil, servicio, mínimos,
        pagos, entrega o políticas y el contexto del turno no basta.
        No inventes si no hay hits.
        """
        hits = await retrieve_knowledge(ctx.context.db, query)
        if not hits:
            return (
                "Sin resultados en knowledge. Aplica políticas duras y, si hace "
                "falta un dato de precio/inventario, escala a humano."
            )
        return format_hits(hits)

    @function_tool
    async def send_catalog(
        ctx: RunContextWrapper[BotContext],
    ) -> str:
        """
        Envía al cliente el PDF de la Carta de Presentación GIA (catálogo de
        líneas: aceros planos, acanalados, tubería industrial, varilla, alambre).
        Usa cuando pidan catálogo, carta de presentación, brochure o el PDF de
        productos GIA. NO la uses para la lista de precios mensual ni para la
        presentación corporativa / planes 2027. Después confirma en texto y
        pregunta qué material y tonelaje buscan.
        """
        if ctx.context.sandbox:
            return await sandbox_send_catalog(ctx.context)
        return await deliver_catalog(ctx.context)

    @function_tool
    async def check_sales_hours(
        ctx: RunContextWrapper[BotContext],
        weekday: str = "",
        hour: int = -1,
        minute: int = 0,
    ) -> str:
        """
        Reloj y horario de asesores de GIA (Ciudad de México).
        Úsala SIEMPRE antes de decir cuándo un asesor puede contactar.
        Si el cliente propone un momento, pasa weekday (lunes…domingo) y hour (0–23).
        No inventes franjas. El horario de planta (L-V 9–16) NO es el de ventas.
        """
        return check_proposed_slot(weekday=weekday, hour=hour, minute=minute)

    return [
        create_lead,
        escalate_to_human,
        search_knowledge,
        send_catalog,
        check_sales_hours,
    ]


def _model_settings_for_openai(model_id: str):
    """Settings recomendados por el SDK para gpt-5.* en Responses (tools + baja latencia)."""
    from agents import ModelSettings
    from openai.types.shared import Reasoning

    if "gpt-5" in model_id.lower() or "luna" in model_id.lower() or "sol" in model_id.lower():
        return ModelSettings(
            reasoning=Reasoning(effort="none"),
            verbosity="low",
        )
    return None


def build_gia_agent(instructions: str, runtime: Optional[LlmRuntime] = None):
    from agents import Agent

    model_name = (runtime.agent_model if runtime else get_settings().agent_model) or ""
    transport, model_id = _parse_model(model_name)
    api_key = _resolve_api_key(model_name, runtime)

    if transport == "openai_responses":
        from agents.models.openai_responses import OpenAIResponsesModel
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        model = OpenAIResponsesModel(model=model_id, openai_client=client)
        model_settings = _model_settings_for_openai(model_id)
        logger.info(
            "gia_agent_model",
            transport="openai_responses",
            model=model_id,
        )
    else:
        from agents.extensions.models.litellm_model import LitellmModel

        model = LitellmModel(model=model_id, api_key=api_key)
        model_settings = None
        logger.info(
            "gia_agent_model",
            transport="litellm",
            model=model_id,
        )

    agent_kwargs = {
        "name": "GIA Sales Assistant",
        "instructions": instructions,
        "model": model,
        "tools": _build_tools(),
    }
    if model_settings is not None:
        agent_kwargs["model_settings"] = model_settings
    return Agent[BotContext](**agent_kwargs)


async def run_gia_agent(
    *,
    ctx: BotContext,
    user_message: str,
    history_messages: Optional[List[Any]] = None,
) -> str:
    """Ejecuta el agente y devuelve el texto de respuesta al cliente."""
    from agents import Runner

    instructions = await build_agent_instructions(ctx.db)
    instructions = f"{instructions}\n\n---\n\n{hours_prompt_block()}"
    if ctx.fresh_cycle:
        instructions = f"{instructions}\n\n---\n\n{FRESH_CYCLE_INSTRUCTION}"
    elif _conversation_handed_off(ctx.conversation) or ctx.handed_off:
        ctx.handed_off = True
        instructions = (
            f"{instructions}\n\n---\n\n"
            "ESTADO: Esta conversación ya fue escalada antes. Puedes volver a "
            "llamar create_lead (handed_off=true) o escalate_to_human si el "
            "cliente pide de nuevo un asesor, cambió el requerimiento o hace "
            "falta re-asignar en Chatwoot. Si solo confirma o repite la petición, "
            "responde en UNA línea breve; no repitas el mismo discurso de "
            "canalización en cada turno. "
            "PROHIBIDO: 'hoy mismo', 'le marcará', 'le llamará', prometer "
            "cotización o respuesta el mismo día. El seguimiento es por mensaje "
            "en este chat, en horario laboral (usa check_sales_hours si dudas)."
        )
    hits = await retrieve_knowledge(ctx.db, user_message)
    retrieved = format_hits(hits)
    runtime = await get_llm_runtime(ctx.db)
    agent = build_gia_agent(instructions, runtime)
    settings = get_settings()
    hist = list(history_messages or [])[-(settings.agent_max_history_messages) :]
    transcript = history_to_input(hist)
    parts: List[str] = []
    if retrieved:
        parts.append(retrieved)
    if transcript:
        parts.append(
            f"Historial reciente:\n{transcript}\n\n"
            f"Nuevo mensaje del cliente:\n{user_message}\n\n"
            "Responde solo el texto para el cliente (sin prefijos). "
            "Un mensaje si es la misma idea. Parte con una línea --- "
            "solo si un asesor en WhatsApp mandaría otro mensaje aparte."
        )
    else:
        parts.append(user_message)
    prompt = "\n\n".join(parts)

    result = await Runner.run(agent, prompt, context=ctx)
    text = (result.final_output or "").strip()
    if not text:
        handed_off = ctx.handed_off or _conversation_handed_off(ctx.conversation)
        text = _empty_reply_fallback(handed_off=handed_off)
        logger.warning(
            "gia_agent_empty_output",
            conversation_id=ctx.conversation.id,
            handed_off=handed_off,
        )
    return text
