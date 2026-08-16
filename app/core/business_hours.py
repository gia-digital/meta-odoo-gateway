"""Horario laboral de ventas (orientativo, no es SLA ni promesa)."""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.core.config import get_settings

WEEKDAY_START = time(8, 0)
WEEKDAY_END = time(19, 0)
SATURDAY_START = time(9, 0)
SATURDAY_END = time(13, 0)

HOURS_LABEL = (
    "lunes a viernes de 8:00 a 19:00 y sábados de 9:00 a 13:00 "
    "(horario Ciudad de México)"
)


def _timezone() -> ZoneInfo:
    name = (get_settings().display_timezone or "America/Mexico_City").strip()
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("America/Mexico_City")


def local_now(now: datetime | None = None) -> datetime:
    tz = _timezone()
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        return current.replace(tzinfo=tz)
    return current.astimezone(tz)


def is_within_hours(now: datetime | None = None) -> bool:
    current = local_now(now)
    weekday = current.weekday()
    clock = current.timetz().replace(tzinfo=None)
    if weekday <= 4:
        return WEEKDAY_START <= clock < WEEKDAY_END
    if weekday == 5:
        return SATURDAY_START <= clock < SATURDAY_END
    return False


def hours_prompt_block(now: datetime | None = None) -> str:
    """Bloque dinámico para el system prompt (no cachear con las instrucciones)."""
    if is_within_hours(now):
        status = "AHORA estamos DENTRO del horario laboral de ventas."
        advise = (
            "Un asesor PUEDE tomar el hilo; no prometas que contestará de inmediato "
            "ni digas 'en breve'. Tú sigues atendiendo hasta que un humano escriba "
            "al cliente. Mirar o asignar el ticket no te calla."
        )
    else:
        status = "AHORA estamos FUERA del horario laboral de ventas."
        advise = (
            "No digas 'en breve' ni prometas tiempo de respuesta. "
            f"Si el cliente pide un asesor, indica que pueden atenderle en {HOURS_LABEL}; "
            "no es una promesa. Tú sigues ayudando (catálogo, materiales, requerimiento)."
        )
    return (
        f"HORARIO LABORAL DE VENTAS (orientativo, no es SLA): {HOURS_LABEL}.\n"
        f"{status}\n{advise}"
    )


def client_handoff_guidance(now: datetime | None = None) -> str:
    """Instrucción al LLM tras abrir el ticket (el bot sigue contestando)."""
    if is_within_hours(now):
        return (
            "El ticket quedó abierto para un asesor; tú SIGUES atendiendo hasta que "
            "un humano escriba al cliente. Di que un asesor de GIA puede tomar el chat; "
            "no prometas un tiempo exacto ni digas 'en breve'."
        )
    return (
        "El ticket quedó abierto para un asesor; tú SIGUES atendiendo hasta que "
        "un humano escriba al cliente. Di que un asesor puede atenderle en "
        f"{HOURS_LABEL}; no es una promesa de respuesta inmediata. Nunca digas 'en breve'."
    )
