"""Agrupa textos libres de product_interest en etiquetas de material legibles."""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFD", text or "")
    without_marks = "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", without_marks).casefold()


def _detect_g_grade(text: str) -> str:
    norm = _norm(text)
    has_g60 = bool(re.search(r"\bg\s*60\b|\bg60\b", norm))
    has_g90 = bool(re.search(r"\bg\s*90\b|\bg90\b", norm))
    if has_g60 and has_g90:
        return "G60/G90"
    if has_g90:
        return "G90"
    if has_g60:
        return "G60"
    return ""


def _extract_caliber(text: str) -> Optional[str]:
    """Devuelve un calibre corto solo cuando hay uno claro."""
    norm = _norm(text)

    single = re.search(r"(?:cal\.?|calibre)\s*(\d{1,2}|reforzado)\b", norm)
    if single:
        return single.group(1)

    multi = re.search(r"calibres\s+([\d,\sy\-–/\"']+)", norm)
    if multi:
        nums = re.findall(r"\b(\d{1,2})\b", multi.group(1))
        if len(nums) == 1:
            return nums[0]
    return None


def _with_caliber(base: str, text: str) -> str:
    caliber = _extract_caliber(text)
    if caliber:
        return f"{base} cal. {caliber}"
    return base


def _fallback_label(text: str) -> str:
    head = re.split(r"[;,]", text, maxsplit=1)[0].strip()
    head = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:piezas?|pzas?|tons?|toneladas?|metros?|m\b|kg)\b",
        "",
        head,
        flags=re.IGNORECASE,
    )
    head = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:['\"]|pulg(?:adas?)?)\b.*",
        "",
        head,
        flags=re.IGNORECASE,
    )
    head = re.sub(r"\s{2,}", " ", head).strip(" ,.-")
    if len(head) > 48:
        head = head[:45].rstrip(" ,.-") + "…"
    return head or text.strip()


def group_material_label(raw: str) -> str:
    """Normaliza product_interest para gráficos: producto + calibre opcional."""
    text = (raw or "").strip()
    if not text:
        return text

    norm = _norm(text)

    if re.search(r"steel\s*deck|deck\s*25|\bdeck\b", norm):
        return _with_caliber("Steel Deck", text)

    acanalado_profiles = (
        (r"r-?\s*101|\br101\b", "Lámina acanalada R-101"),
        (r"r-?\s*72|\br72\b", "Lámina acanalada R-72"),
        (r"kr-?\s*18|\bkr18\b", "Lámina acanalada KR-18"),
        (r"rn-?\s*100|\brn100\b", "Lámina acanalada RN-100/35"),
        (r"o-?\s*100|o-?\s*30", "Lámina acanalada O-100 y O-30"),
    )
    for pattern, label in acanalado_profiles:
        if re.search(pattern, norm):
            return _with_caliber(label, text)

    if "acanalad" in norm:
        return _with_caliber("Lámina acanalada", text)

    if re.search(r"ovalad", norm):
        return _with_caliber("Tubería ovalada", text)

    if re.search(r"tubo\s+cuadrad|tubo\s+rectang|cuadrad.*tubo|tubo\s+cuadrado", norm):
        return _with_caliber("Tubería cuadrada / rectangular", text)

    if re.search(r"tuberia|tubo|tubular|\bpipe\b", norm):
        return _with_caliber("Tubería industrial de acero negro", text)

    if ("lamina" in norm or "lámina" in text.lower()) and (
        "galvaniz" in norm or _detect_g_grade(text)
    ):
        grade = _detect_g_grade(text)
        base = f"Lámina galvanizada {grade}".strip() if grade else "Lámina galvanizada"
        return _with_caliber(base, text)

    if "pintro" in norm and "acanalad" not in norm:
        return _with_caliber("Lámina Pintro", text)

    if re.search(r"galvanneal|galvaneel", norm):
        return _with_caliber("Lámina Galvanneal", text)
    if "electrogalvaniz" in norm or re.search(r"\beg\b", norm):
        return _with_caliber("Lámina electrogalvanizada", text)
    if "ecogal" in norm or "zintroalum" in norm:
        return _with_caliber("Lámina Ecogal / zintroalum", text)
    if re.search(r"\bhrpo\b|caliente decapad|pickled", norm):
        return _with_caliber("Lámina caliente decapada (HRPO)", text)
    if re.search(r"\bcr\b|fria recocid|cold rolled|lamina fria", norm):
        return _with_caliber("Lámina fría recocida (CR)", text)
    if re.search(r"\bhr\b|caliente|hot rolled|antiderrapante", norm):
        return _with_caliber("Lámina caliente (HR)", text)
    if "lamina" in norm or "lámina" in text.lower():
        return _with_caliber("Lámina", text)

    if "varilla" in norm:
        return _with_caliber("Varilla", text)
    if "alambre" in norm:
        return _with_caliber("Alambre pulido y galvanizado", text)
    if "monten" in norm or "montén" in text.lower():
        return _with_caliber("Monten", text)
    if re.search(r"angulo camero|ángulo camero", text.lower()):
        return _with_caliber("Ángulo camero", text)

    return _fallback_label(text)
