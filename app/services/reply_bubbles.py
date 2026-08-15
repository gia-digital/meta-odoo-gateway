"""Parte la respuesta del agente solo si el LLM marcó burbujas."""
from __future__ import annotations

import re
from typing import List

# Línea que solo es --- / — / |||. El modelo la pone a propósito.
_EXPLICIT = re.compile(r"\n\s*(?:---+|—{2,}|\|{3})\s*\n")


def split_reply_bubbles(text: str, *, max_bubbles: int = 4) -> List[str]:
    """Corta únicamente por --- / |||. Párrafos o puntos no se parten solos."""
    raw = (text or "").strip()
    if not raw:
        return []

    cap = max(1, int(max_bubbles))
    if not _EXPLICIT.search(raw):
        return [raw]

    parts = [p.strip() for p in _EXPLICIT.split(raw) if p.strip()]
    if not parts:
        return [raw]
    if len(parts) <= cap:
        return parts
    head = parts[: cap - 1]
    tail = "\n\n".join(parts[cap - 1 :])
    return head + [tail]


def first_send_wait_seconds(
    text: str,
    *,
    elapsed: float,
    think: float,
    chars_per_sec: float,
    min_total: float,
    max_wait: float,
    jitter: float = 0.0,
) -> float:
    """
    Segundos extra antes del primer envío.
    El tiempo del LLM cuenta; el total se mantiene entre min_total y max_wait.
    """
    cps = max(float(chars_per_sec), 1.0)
    lo = max(0.0, float(min_total))
    hi = max(lo, float(max_wait))
    natural = max(0.0, float(think)) + len(text or "") / cps
    target = min(hi, max(lo, natural) + max(0.0, float(jitter)))
    leftover = target - max(0.0, float(elapsed))
    return max(0.0, leftover)


def next_bubble_wait_seconds(
    text: str,
    *,
    chars_per_sec: float,
    min_wait: float,
    max_wait: float,
) -> float:
    """Pausa entre burbujas: como si escribiera el siguiente mensaje."""
    cps = max(float(chars_per_sec), 1.0)
    typed = 0.35 + len(text or "") / cps
    return min(max(0.0, float(max_wait)), max(float(min_wait), typed))
