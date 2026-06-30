"""Tests de seguridad: verificación de firma de Meta."""
import hashlib
import hmac

from app.core.security import verify_meta_signature


def _sign(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()


def test_valid_signature_passes(monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", "test_secret")
    # Re-importar settings cache
    from app.core.config import get_settings
    get_settings.cache_clear()

    payload = b'{"object":"whatsapp_business_account","entry":[]}'
    sig = _sign(payload, "test_secret")
    assert verify_meta_signature(payload, sig) is True


def test_invalid_signature_fails(monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", "test_secret")
    from app.core.config import get_settings
    get_settings.cache_clear()

    payload = b'{"object":"whatsapp_business_account","entry":[]}'
    bad_sig = "sha256=" + "0" * 64
    assert verify_meta_signature(payload, bad_sig) is False


def test_missing_signature_fails():
    payload = b'{"object":"whatsapp_business_account","entry":[]}'
    assert verify_meta_signature(payload, None) is False
    assert verify_meta_signature(payload, "") is False
    assert verify_meta_signature(payload, "invalid_format") is False
