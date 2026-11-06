"""Sanitizado de meta/razonamiento filtrado al cliente."""
from __future__ import annotations

from app.services.reply_sanitize import sanitize_customer_reply


def test_strips_english_menudeo_planning_prefix():
    raw = (
        "Two sheets is far below the 3-ton minimum, so this is a menudeo case. "
        "Short reply, no lead, no distributors, no contact data.\n\n"
        "Buenas tardes. Nosotros manejamos puro mayoreo desde 3 toneladas, "
        "así que dos láminas no las podemos surtir. Si tiene más partidas o "
        "medidas que pueda juntar para llegar al mínimo, con gusto lo revisamos."
    )
    cleaned = sanitize_customer_reply(raw)
    assert cleaned.startswith("Buenas tardes")
    assert "Short reply" not in cleaned
    assert "menudeo case" not in cleaned
    assert "no lead" not in cleaned


def test_keeps_normal_spanish_reply():
    text = "Va, cal. 20. ¿La ocupa en hoja de 3x8 u otra medida?"
    assert sanitize_customer_reply(text) == text


def test_keeps_multi_paragraph_customer_spanish():
    text = (
        "Manejamos puro mayoreo desde 3 toneladas.\n\n"
        "Si consolida partidas con gusto lo vemos."
    )
    assert sanitize_customer_reply(text) == text


def test_strips_thinking_tags():
    raw = (
        "<thinking>Menudeo bajo mínimo; no lead.</thinking>\n\n"
        "Manejamos puro mayoreo, desde 3 toneladas. ¿Alcanza a consolidar?"
    )
    cleaned = sanitize_customer_reply(raw)
    assert cleaned.startswith("Manejamos puro mayoreo")
    assert "thinking" not in cleaned.lower()
    assert "no lead" not in cleaned.lower()


def test_strips_note_prefix_single_paragraph():
    raw = "Note: no escalate.\n\nClaro, ¿qué calibre ocupa?"
    cleaned = sanitize_customer_reply(raw)
    assert cleaned == "Claro, ¿qué calibre ocupa?"


def test_strips_spanish_meta_prefix():
    raw = (
        "Caso menudeo, respuesta corta, sin lead ni distribuidores.\n\n"
        "Manejamos puro mayoreo desde 3 toneladas. ¿Alcanza a consolidar?"
    )
    cleaned = sanitize_customer_reply(raw)
    assert cleaned.startswith("Manejamos puro mayoreo")
    assert "sin lead" not in cleaned


def test_empty_stays_empty():
    assert sanitize_customer_reply("") == ""
    assert sanitize_customer_reply("   ") == ""
