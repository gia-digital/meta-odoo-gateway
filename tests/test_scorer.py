"""Tests del motor de scoring."""
from datetime import datetime
from types import SimpleNamespace

from app.services.lead_scorer import score_conversation


def make_message(text: str, direction: str = "inbound"):
    """Crea un objeto compatible con Message para tests, sin tocar la DB."""
    return SimpleNamespace(
        body=text,
        direction=SimpleNamespace(value=direction),
        created_at=datetime.utcnow(),
    )


def test_empty_conversation_returns_zero():
    result = score_conversation([])
    assert result.total == 0
    assert result.create_lead is False


def test_single_casual_message_low_score():
    msgs = [make_message("Hola, buenos días")]
    result = score_conversation(msgs)
    assert result.total < 6
    assert result.create_lead is False


def test_qualified_lead_triggers_creation():
    msgs = [
        make_message("Hola"),
        make_message("Me interesa lámina galvanizada"),
        make_message("Mi presupuesto es de $5000 USD, unas 8 toneladas"),
        make_message("Lo necesito para este mes"),
    ]
    result = score_conversation(msgs)
    assert result.total >= 6
    assert result.create_lead is True


def test_hot_lead_triggers_handoff():
    msgs = [
        make_message("Hola, quiero cotizar tubería industrial"),
        make_message("Mi presupuesto es $10,000 MXN, unas 5 toneladas"),
        make_message("Es urgente, lo necesito hoy"),
        make_message("Mi email es juan@empresa.com"),
        make_message("Quiero hablar con un asesor por favor"),
    ]
    result = score_conversation(msgs)
    assert result.total >= 9
    assert result.create_lead is True
    assert result.notify_human is True


def test_outbound_messages_not_counted():
    msgs = [
        make_message("Hola, ¿en qué puedo ayudarte?", direction="outbound"),
        make_message("Tenemos los siguientes materiales...", direction="outbound"),
    ]
    result = score_conversation(msgs)
    assert result.total == 0


def test_evidence_is_captured():
    msgs = [
        make_message("Quiero cotizar lámina galvanizada urgente"),
    ]
    result = score_conversation(msgs)
    matched = [s for s in result.signals if s.matched]
    assert any("urgente" in (s.evidence or "") for s in matched)
    assert any(
        "cotizar" in (s.evidence or "") or "lámina" in (s.evidence or "")
        for s in matched
    )


def test_email_detection_in_shared_contact():
    msgs = [
        make_message("Hola"),
        make_message("Hola"),
        make_message("Mi correo es juan.perez@empresa.com"),
    ]
    result = score_conversation(msgs)
    contact_signal = next(s for s in result.signals if s.name == "shared_contact")
    assert contact_signal.matched
    assert "juan.perez@empresa.com" in (contact_signal.evidence or "")
