"""Perfil de identidad estable entre ciclos (nombre, empresa, teléfono, correo)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Channel, ContactProfile, Conversation
from app.models.db import commit_with_retry


def _clip(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def _set_if_value(obj: object, attr: str, value: Optional[str]) -> bool:
    """Escribe solo si hay valor nuevo; no borra lo ya guardado. Devuelve si cambió."""
    if not value:
        return False
    if getattr(obj, attr, None) == value:
        return False
    setattr(obj, attr, value)
    return True


async def get_contact_profile(
    db: AsyncSession,
    channel: Channel,
    external_user_id: str,
) -> Optional[ContactProfile]:
    result = await db.execute(
        select(ContactProfile).where(
            ContactProfile.channel == channel,
            ContactProfile.external_user_id == external_user_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_contact_profile(
    db: AsyncSession,
    *,
    channel: Channel,
    external_user_id: str,
    display_name: Optional[str] = None,
    company: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    commit: bool = True,
) -> ContactProfile:
    """Crea o actualiza el perfil. Campos vacíos no pisan valores existentes."""
    name = _clip(display_name, 255)
    company_v = _clip(company, 255)
    phone_v = _clip(phone, 64)
    email_v = _clip(email, 255)

    profile = await get_contact_profile(db, channel, external_user_id)
    if profile is None:
        profile = ContactProfile(
            channel=channel,
            external_user_id=external_user_id,
            display_name=name,
            company=company_v,
            phone=phone_v,
            email=email_v,
        )
        db.add(profile)
        if commit:
            await commit_with_retry(db)
            await db.refresh(profile)
        return profile

    changed = False
    changed |= _set_if_value(profile, "display_name", name)
    changed |= _set_if_value(profile, "company", company_v)
    changed |= _set_if_value(profile, "phone", phone_v)
    changed |= _set_if_value(profile, "email", email_v)
    if changed and commit:
        await commit_with_retry(db)
        await db.refresh(profile)
    return profile


def apply_profile_to_conversation(
    conversation: Conversation, profile: Optional[ContactProfile]
) -> None:
    """Rellena huecos del ciclo actual con el perfil; no pisa lo ya capturado."""
    if profile is None:
        return
    if not conversation.user_name and profile.display_name:
        conversation.user_name = profile.display_name
    if not getattr(conversation, "user_company", None) and profile.company:
        conversation.user_company = profile.company
    if not conversation.user_phone and profile.phone:
        conversation.user_phone = profile.phone
    if not conversation.user_email and profile.email:
        conversation.user_email = profile.email


def sync_conversation_contact_fields(
    conversation: Conversation,
    *,
    user_name: Optional[str] = None,
    user_company: Optional[str] = None,
    user_phone: Optional[str] = None,
    user_email: Optional[str] = None,
) -> None:
    """Actualiza campos de contacto del ciclo cuando llegan valores nuevos."""
    if user_name:
        conversation.user_name = _clip(user_name, 255)
    if user_company:
        conversation.user_company = _clip(user_company, 255)
    if user_phone:
        conversation.user_phone = _clip(user_phone, 64)
    if user_email:
        conversation.user_email = _clip(user_email, 255)


def format_known_contact_block(
    *,
    user_name: Optional[str] = None,
    user_company: Optional[str] = None,
    user_phone: Optional[str] = None,
    user_email: Optional[str] = None,
) -> str:
    """Bloque de instrucciones con identidad conocida para el LLM."""
    lines = []
    if (user_name or "").strip():
        lines.append(f"- Nombre: {user_name.strip()}")
    if (user_company or "").strip():
        lines.append(f"- Empresa: {user_company.strip()}")
    if (user_phone or "").strip():
        lines.append(f"- Teléfono: {user_phone.strip()}")
    if (user_email or "").strip():
        lines.append(f"- Correo: {user_email.strip()}")
    if not lines:
        return ""
    return (
        "DATOS DE CONTACTO GUARDADOS (identidad estable entre visitas; "
        "no son el pedido actual):\n"
        + "\n".join(lines)
        + "\n"
        "Úsalos al pedir o confirmar datos de contacto. Si faltaba pedirlos o "
        "es un ciclo nuevo, confirma en corto si siguen igual en lugar de "
        "volver a pedirlos. No inventes campos que no estén listados."
    )
