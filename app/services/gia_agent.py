"""
Agente conversacional GIA vía OpenAI Agents SDK.

- OpenAI → Responses API nativa (OpenAIResponsesModel). Preferido para gpt-5.*.
- Anthropic u otros → LiteLLM (chat completions del proveedor).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.llm_runtime import LlmRuntime, get_llm_runtime
from app.core.logging import get_logger
from app.models.conversation import Channel, Conversation, QualificationSource
from app.services.agent_knowledge import build_agent_instructions
from app.services.catalog_document import deliver_catalog
from app.services.chatwoot_client import ChatwootClient
from app.services.conversation import ConversationService
from app.services.knowledge.retriever import format_hits, retrieve_knowledge

logger = get_logger(__name__)


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
    extra: dict = field(default_factory=dict)


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
    ) -> str:
        """
        Registra un prospecto calificado en el servidor de GIA para que ventas dé seguimiento.
        Usa SOLO si el material es del catálogo GIA (acero al carbono) y hay mayoreo
        (mín. ~1 ton/partida y 3 ton total) o el cliente pidió hablar con un asesor.
        NO uses para inoxidable, aluminio, ni pedidos de menudeo/pocas láminas bajo mínimo.
        """
        bot = ctx.context
        service = ConversationService(bot.db)
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
            try:
                async with ChatwootClient() as cw:
                    await cw.handoff_to_human(
                        bot.chatwoot_conversation_id,
                        note=(
                            f"Lead creado y escalado. Motivo: {reason}. "
                            f"{summary}".strip()
                        ),
                    )
            except Exception as exc:
                logger.error(
                    "agent_create_lead_handoff_failed",
                    error=str(exc),
                    chatwoot_conversation_id=bot.chatwoot_conversation_id,
                )
        logger.info(
            "agent_tool_create_lead",
            conversation_id=conv.id,
            handed_off=handed_off,
        )
        return (
            f"Lead registrado (id interno {conv.id}, status={conv.status.value}). "
            "Confirma al cliente que un asesor le contactará; no menciones IDs internos."
        )

    @function_tool
    async def escalate_to_human(
        ctx: RunContextWrapper[BotContext],
        reason: str,
    ) -> str:
        """
        Escala la conversación a un asesor humano en Chatwoot (abre el ticket).
        Usa cuando hace falta cotización formal, datos bancarios, reclamación,
        cliente con vendedor, o el cliente pide hablar con una persona.
        """
        bot = ctx.context
        service = ConversationService(bot.db)
        await service.mark_handed_off(bot.conversation, reason=reason)
        bot.handed_off = True
        try:
            async with ChatwootClient() as cw:
                await cw.handoff_to_human(
                    bot.chatwoot_conversation_id,
                    note=f"Escalado por el agente. Motivo: {reason}",
                )
        except Exception as exc:
            logger.error(
                "agent_escalate_chatwoot_failed",
                error=str(exc),
                chatwoot_conversation_id=bot.chatwoot_conversation_id,
            )
            return (
                f"Conversación marcada como escalada en el gateway, pero Chatwoot "
                f"falló al abrir el ticket: {exc}. Indica al cliente que un asesor "
                "le contactará en breve."
            )
        logger.info(
            "agent_tool_escalate",
            conversation_id=bot.conversation.id,
            reason=reason,
        )
        return (
            "Conversación entregada a un asesor humano en Chatwoot. "
            "Di al cliente que en breve le atenderá un asesor de GIA."
        )

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
        return await deliver_catalog(ctx.context)

    return [create_lead, escalate_to_human, search_knowledge, send_catalog]


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
        text = (
            "Gracias por su mensaje. Un momento, por favor; "
            "si prefiere, puedo canalizarle con un asesor de GIA."
        )
    return text
