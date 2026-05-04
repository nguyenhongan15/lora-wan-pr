"""
tests/unit/test_webhook_security.py — Unit test cho core.webhook_security.
"""

from __future__ import annotations

import hmac
from hashlib import sha256

from core.webhook_security import verify_webhook_signature


SECRET = "test_secret_xyz"
BODY   = b'{"deviceEui":"abc","rssi":-95}'


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, sha256).hexdigest()


def test_verify_webhook_signature_correct_signature_returns_true():
    # Arrange
    valid = _sign(SECRET, BODY)

    # Act
    result = verify_webhook_signature(BODY, valid, SECRET)

    # Assert
    assert result is True


def test_verify_webhook_signature_tampered_body_returns_false():
    # Arrange — body đã bị sửa nhưng signature cũ
    valid_for_original = _sign(SECRET, BODY)
    tampered_body      = BODY + b" TAMPERED"

    # Act
    result = verify_webhook_signature(tampered_body, valid_for_original, SECRET)

    # Assert
    assert result is False


def test_verify_webhook_signature_missing_header_returns_false():
    # Arrange + Act
    result = verify_webhook_signature(BODY, None, SECRET)

    # Assert
    assert result is False