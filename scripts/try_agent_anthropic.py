"""Prueba local del agente GIA (Anthropic vía LiteLLM), sin Chatwoot."""
from __future__ import annotations

import asyncio
import sys

from app.core.config import get_settings
from app.models.conversation import Channel
from app.models.db import SessionLocal, init_db
from app.models.schemas import NormalizedMessage
from app.services.conversation import ConversationService
from app.services.gia_agent import BotContext, run_gia_agent


MESSAGES = [
    "Hola, buen día.",
    "¿Venden acero inoxidable?",
    (
        "Necesito cotizar 10 toneladas de lámina galvanizada para techos "
        "en CDMX, para este mes. Me llamo Juan Pérez."
    ),
]


async def main() -> int:
    settings = get_settings()
    print(f"Modelo: {settings.agent_model}")
    print(f"Anthropic key: {'sí' if settings.anthropic_api_key else 'NO'}")
    print()

    await init_db()
    async with SessionLocal() as db:
        service = ConversationService(db)
        conv = await service.get_or_create(
            channel=Channel.whatsapp,
            external_user_id="5215510000002",
            user_name="Juan Pérez",
        )
        print(f"Conversación #{conv.id} status={conv.status.value}")
        print()

        for i, text in enumerate(MESSAGES, 1):
            print(f"--- Cliente ({i}) ---")
            print(text)
            print()
            ctx = BotContext(
                db=db,
                conversation=conv,
                channel=Channel.whatsapp,
                external_user_id=conv.external_user_id,
                chatwoot_conversation_id=0,
                user_name=conv.user_name,
                user_phone=conv.user_phone,
            )
            try:
                reply = await run_gia_agent(
                    ctx=ctx,
                    user_message=text,
                    history_messages=conv.messages,
                )
            except Exception as exc:
                print(f"ERROR: {type(exc).__name__}: {exc}")
                return 1
            print("--- Agente ---")
            print(reply)
            print()
            await service.add_inbound_message(
                conv,
                NormalizedMessage(
                    channel="whatsapp",
                    external_user_id=conv.external_user_id,
                    text=text,
                    user_name=conv.user_name,
                ),
            )
            await service.add_outbound_message(conv, reply)
            await db.refresh(conv, ["messages"])

        await db.refresh(conv)
        print("--- Estado final ---")
        print(f"status={conv.status.value} source={conv.qualification_source.value}")
        print(f"interest={conv.product_interest} reason={conv.qualification_reason}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
