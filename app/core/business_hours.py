"""Horario laboral de ventas (orientativo, no es SLA ni promesa)."""
from __future__ import annotations

from datetime import datetime, timedelta, time
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

WEEKDAYS_ES = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)
MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

_WEEKDAY_ALIASES = {
    "lunes": 0,
    "lun": 0,
    "martes": 1,
    "mar": 1,
    "miercoles": 2,
    "miércoles": 2,
    "mie": 2,
    "jueves": 3,
    "jue": 3,
    "viernes": 4,
    "vie": 4,
    "sabado": 5,
    "sábado": 5,
    "sab": 5,
    "domingo": 6,
    "dom": 6,
}


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


def _clock(current: datetime) -> time:
    return current.timetz().replace(tzinfo=None)


def is_within_hours(now: datetime | None = None) -> bool:
    current = local_now(now)
    weekday = current.weekday()
    clock = _clock(current)
    if weekday <= 4:
        return WEEKDAY_START <= clock < WEEKDAY_END
    if weekday == 5:
        return SATURDAY_START <= clock < SATURDAY_END
    return False


def format_local(now: datetime | None = None) -> str:
    current = local_now(now)
    weekday = WEEKDAYS_ES[current.weekday()]
    month = MONTHS_ES[current.month - 1]
    return (
        f"{weekday} {current.day} de {month} de {current.year}, "
        f"{current.strftime('%H:%M')}"
    )


def next_open_at(now: datetime | None = None) -> datetime:
    """Inicio de la ventana de ventas actual (si está abierta) o la siguiente."""
    current = local_now(now)
    if is_within_hours(current):
        return current
    clock = _clock(current)
    wd = current.weekday()

    def at_day(base: datetime, days: int, hour: int, minute: int = 0) -> datetime:
        return (base + timedelta(days=days)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )

    if wd <= 4:
        if clock < WEEKDAY_START:
            return at_day(current, 0, 8)
        if wd < 4:
            return at_day(current, 1, 8)
        return at_day(current, 1, 9)
    if wd == 5:
        if clock < SATURDAY_START:
            return at_day(current, 0, 9)
        return at_day(current, 2, 8)
    return at_day(current, 1, 8)


def format_next_open(now: datetime | None = None) -> str:
    nxt = next_open_at(now)
    if is_within_hours(now):
        current = local_now(now)
        end = WEEKDAY_END if current.weekday() <= 4 else SATURDAY_END
        return (
            f"ahora (ventana abierta hasta las {end.strftime('%H:%M')} "
            "hora Ciudad de México)"
        )
    return format_local(nxt)


def parse_weekday(raw: str) -> int | None:
    key = (raw or "").strip().casefold()
    if not key:
        return None
    key = key.replace("é", "e").replace("á", "a")
    return _WEEKDAY_ALIASES.get(key)


def proposed_datetime(
    *,
    weekday: str = "",
    hour: int = -1,
    minute: int = 0,
    now: datetime | None = None,
) -> datetime | None:
    """Arma un datetime esta semana (o la siguiente si el día ya pasó)."""
    current = local_now(now)
    wd = parse_weekday(weekday)
    if wd is None and hour < 0:
        return None
    target_wd = current.weekday() if wd is None else wd
    target_hour = _clock(current).hour if hour < 0 else hour
    target_minute = _clock(current).minute if hour < 0 else max(0, min(59, minute))
    if not (0 <= target_hour <= 23):
        return None
    delta = (target_wd - current.weekday()) % 7
    proposed = current.replace(
        hour=target_hour, minute=target_minute, second=0, microsecond=0
    ) + timedelta(days=delta)
    if proposed < current - timedelta(minutes=1):
        proposed += timedelta(days=7)
    return proposed


def availability_snapshot(now: datetime | None = None) -> str:
    current = local_now(now)
    open_now = is_within_hours(current)
    status = "ABIERTA" if open_now else "CERRADA"
    nxt = format_next_open(current)
    return (
        f"Ahora: {format_local(current)} (Ciudad de México).\n"
        f"Atención de ventas: {status}.\n"
        f"Horario de asesores: {HOURS_LABEL}. Domingo no hay atención comercial.\n"
        f"Próxima ventana: {nxt}.\n"
        "Esto es orientativo, NO es una promesa ni un SLA. "
        "NUNCA inventes una franja ('entre 11 y 16', etc.). "
        "NO uses el horario de recolección en planta (L-V 9:00–16:00): "
        "eso no es horario de asesores."
    )


def hours_prompt_block(now: datetime | None = None) -> str:
    """Bloque dinámico para el system prompt (no cachear con las instrucciones)."""
    snap = availability_snapshot(now)
    if is_within_hours(now):
        status = "AHORA estamos DENTRO del horario laboral de ventas."
        advise = (
            "Un asesor PUEDE tomar el hilo por este chat; no prometas que contestará "
            "de inmediato, hoy mismo, ni digas 'en breve'. El seguimiento es por "
            "mensaje (WhatsApp), no por llamada telefónica: NUNCA digas 'le marcará', "
            "'le llamará' ni 'le contactará hoy'. Tú sigues atendiendo hasta que un "
            "humano escriba al cliente. Antes de hablar de cuándo dará seguimiento un "
            "asesor, usa check_sales_hours."
        )
    else:
        status = "AHORA estamos FUERA del horario laboral de ventas."
        advise = (
            "No digas 'en breve', 'hoy mismo' ni prometas hora o día exacto. "
            "El seguimiento del asesor es por mensaje en este chat, no por llamada: "
            "prohibido 'le marcará' o 'le llamará'. "
            "Si el cliente pide un asesor, di que pueden darle seguimiento en el "
            "próximo horario laboral (la 'Próxima ventana' de arriba); no es promesa. "
            "Tú sigues ayudando ahora. Usa check_sales_hours si dudas o si el "
            "cliente propone un día/hora."
        )
    return (
        f"HORARIO LABORAL DE VENTAS (orientativo, no es SLA):\n{status}\n{snap}\n{advise}"
    )


def client_handoff_guidance(now: datetime | None = None) -> str:
    """Instrucción al LLM tras abrir el ticket (el bot sigue contestando)."""
    snap = availability_snapshot(now)
    if is_within_hours(now):
        say = (
            "Di que un asesor de GIA puede darle seguimiento por este chat en "
            "horario laboral; no prometas tiempo exacto, 'hoy mismo' ni 'en breve'. "
            "NUNCA digas que le marcarán o llamarán: el contacto es por mensaje."
        )
    else:
        say = (
            f"Di que un asesor puede darle seguimiento por este chat a partir de "
            f"{format_next_open(now)} (horario laboral); no prometas 'hoy mismo', "
            "hora exacta ni 'en breve'. NUNCA digas que le marcarán o llamarán."
        )
    return (
        "El ticket quedó abierto para un asesor; tú SIGUES atendiendo hasta que "
        f"un humano escriba al cliente. {say}\n{snap}"
    )


def check_proposed_slot(
    weekday: str = "",
    hour: int = -1,
    minute: int = 0,
    now: datetime | None = None,
) -> str:
    """Texto para el tool: ahora +, si aplica, si una hora propuesta cae en horario."""
    lines = [availability_snapshot(now)]
    proposed = proposed_datetime(
        weekday=weekday, hour=hour, minute=minute, now=now
    )
    if proposed is None:
        lines.append(
            "No se evaluó una hora propuesta (pasa weekday y hour si el cliente "
            "sugiere un momento)."
        )
        return "\n".join(lines)
    open_slot = is_within_hours(proposed)
    label = format_local(proposed)
    if open_slot:
        lines.append(
            f"Hora propuesta ({label}): DENTRO del horario de ventas. "
            "Aun así no prometas que un asesor contestará justo a esa hora."
        )
    else:
        lines.append(
            f"Hora propuesta ({label}): FUERA del horario de ventas. "
            f"La próxima ventana de asesores es {format_next_open(proposed)}."
        )
    return "\n".join(lines)
