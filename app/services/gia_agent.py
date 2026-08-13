"""
Agente conversacional GIA vía OpenAI Agents SDK + LiteLLM.

Soporta Anthropic y OpenAI según AGENT_MODEL (ej. anthropic/claude-... o openai/gpt-...).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.conversation import Channel, Conversation, QualificationSource
from app.services.agent_knowledge import build_agent_instructions
from app.services.chatwoot_client import ChatwootClient
from app.services.conversation import ConversationService

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


def _resolve_api_key(model: str) -> Optional[str]:
    settings = get_settings()
    m = model.lower()
    if m.startswith("anthropic/") or "claude" in m:
        return settings.anthropic_api_key or None
    if m.startswith("openai/") or m.startswith("gpt-"):
        return settings.openai_api_key or None
    return settings.anthropic_api_key or settings.openai_api_key or None


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
        Usa cuando el cliente pidió cotización, compartió volumen/urgencia, o pidió hablar con un asesor.
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
                    await cw.handoff_to_human(bot.chatwoot_conversation_id)
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
                await cw.handoff_to_human(bot.chatwoot_conversation_id)
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

    return [create_lead, escalate_to_human]


def build_gia_agent():
    from agents import Agent
    from agents.extensions.models.litellm_model import LitellmModel

    settings = get_settings()
    model_name = settings.agent_model
    api_key = _resolve_api_key(model_name)
    model = LitellmModel(model=model_name, api_key=api_key)
    return Agent[BotContext](
        name="GIA Sales Assistant",
        instructions=build_agent_instructions(),
        model=model,
        tools=_build_tools(),
    )


async def run_gia_agent(
    *,
    ctx: BotContext,
    user_message: str,
    history_messages: Optional[List[Any]] = None,
) -> str:
    """Ejecuta el agente y devuelve el texto de respuesta al cliente."""
    from agents import Runner

    agent = build_gia_agent()
    settings = get_settings()
    hist = list(history_messages or [])[-(settings.agent_max_history_messages) :]
    transcript = history_to_input(hist)
    if transcript:
        prompt = (
            f"Historial reciente:\n{transcript}\n\n"
            f"Nuevo mensaje del cliente:\n{user_message}\n\n"
            "Responde solo el mensaje para el cliente (sin prefijos)."
        )
    else:
        prompt = user_message

    result = await Runner.run(agent, prompt, context=ctx)
    text = (result.final_output or "").strip()
    if not text:
        text = (
            "Gracias por su mensaje. Un momento, por favor; "
            "si prefiere, puedo canalizarle con un asesor de GIA."
        )
    return text
