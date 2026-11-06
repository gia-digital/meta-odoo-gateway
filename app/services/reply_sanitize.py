"""Quita razonamiento/meta que el LLM a veces antepone al mensaje al cliente."""
from __future__ import annotations

import re

# Etiquetas de "thinking" / scratchpad que algunos modelos emiten.
_THINK_TAGS = re.compile(
    r"<thinking\b[^>]*>.*?</thinking\s*>|"
    r"<think\b[^>]*>.*?</think\s*>|"
    r"</?thinking\b[^>]*>|"
    r"</?think\b[^>]*>",
    re.IGNORECASE | re.DOTALL,
)

# Prefijos explícitos de nota interna.
_META_PREFIX = re.compile(
    r"^(?:note|internal(?:\s+note)?|reasoning|thinking|plan|scratch(?:pad)?|"
    r"meta|analysis|nota(?:\s+interna)?|razonamiento|análisis)\s*[:\-—]\s*",
    re.IGNORECASE,
)

# Frases típicas de planificación / políticas (EN o ES) que no van al cliente.
_META_PHRASE = re.compile(
    r"(?:"
    r"short reply|"
    r"no lead|"
    r"no distributors|"
    r"no contact(?:\s+data)?|"
    r"menudeo case|"
    r"this is a (?:menudeo|wholesale|retail)|"
    r"far below the .{0,40}minimum|"
    r"below the .{0,40}minimum|"
    r"do not (?:create|register|escalate|mention)|"
    r"don't (?:create|register|escalate|mention)|"
    r"respuesta corta|"
    r"sin lead|"
    r"caso menudeo|"
    r"sin distribuidores|"
    r"sin (?:datos de )?contacto|"
    r"no (?:crear|registrar|escalar) lead|"
    r"no create_lead|"
    r"no escalate"
    r")",
    re.IGNORECASE,
)

_ES_MARKERS = re.compile(
    r"[áéíóúüñ¿¡]|"
    r"\b(?:"
    r"nosotros|manejamos|ocupa|calibre|lámina|lamina|toneladas|tonelada|"
    r"buenas|buenos|tardes|días|noches|gracias|usted|ustedes|con\s+gusto|"
    r"asesor|mayoreo|menudeo|partidas|medidas|surti[rv]|revisamos|"
    r"claro|listo|queda|pendiente|hola|qué|que|cómo|como"
    r")\b",
    re.IGNORECASE,
)

_EN_MARKERS = re.compile(
    r"\b(?:"
    r"the|this|that|these|those|is|are|was|were|be|been|being|"
    r"so|far|below|above|minimum|case|short|reply|lead|distributors|"
    r"contact|data|sheets?|tons?|wholesale|retail|should|would|could|"
    r"don't|does|did|will|shall|must|cannot|can't|won't|"
    r"internal|reasoning|thinking|policy|note"
    r")\b",
    re.IGNORECASE,
)


def _looks_like_spanish_customer(text: str) -> bool:
    return bool(_ES_MARKERS.search(text or ""))


def _looks_like_english_heavy(text: str) -> bool:
    en = len(_EN_MARKERS.findall(text or ""))
    es = len(_ES_MARKERS.findall(text or ""))
    if en < 3:
        return False
    return en >= max(3, es * 2)


def _looks_like_meta(paragraph: str) -> bool:
    text = (paragraph or "").strip()
    if not text:
        return True
    if _META_PREFIX.match(text):
        return True
    if _META_PHRASE.search(text):
        return True
    # Bloque en inglés de planificación cuando el resto del mensaje es español.
    if _looks_like_english_heavy(text) and not _looks_like_spanish_customer(text):
        return True
    return False


def sanitize_customer_reply(text: str) -> str:
    """
    Devuelve solo el texto orientado al cliente.

    Recorta etiquetas de thinking y párrafos iniciales de meta/razonamiento
    (p. ej. inglés: "Short reply, no lead…") cuando hay un mensaje usable después.
    """
    raw = (text or "").strip()
    if not raw:
        return ""

    cleaned = _THINK_TAGS.sub("", raw).strip()
    if not cleaned:
        return ""

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", cleaned) if p.strip()]
    if len(paragraphs) <= 1:
        # Un solo bloque: quita prefijo "Note:" si aplica, pero no borres todo.
        only = paragraphs[0] if paragraphs else cleaned
        only = _META_PREFIX.sub("", only).strip()
        return only or cleaned

    start = 0
    while start < len(paragraphs) - 1 and _looks_like_meta(paragraphs[start]):
        start += 1

    kept = paragraphs[start:]
    # Si todo parecía meta pero el último bloque es español al cliente, conserva ese.
    if start > 0 and not any(_looks_like_spanish_customer(p) for p in kept):
        for idx in range(len(paragraphs) - 1, -1, -1):
            if _looks_like_spanish_customer(paragraphs[idx]):
                kept = paragraphs[idx:]
                break

    return "\n\n".join(kept).strip()
