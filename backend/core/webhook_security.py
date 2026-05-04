"""
core/webhook_security.py — HMAC signature verification cho webhook endpoints.

LƯU Ý: đây KHÔNG phải authentication cho user. Đây là mechanism xác minh
nguồn gốc của payload — đảm bảo payload đến từ ChirpStack (có shared secret)
chứ không phải ai đó gửi rác vào endpoint public của webhook.

Đây là yêu cầu bắt buộc cho mọi webhook endpoint, không liên quan đến
việc hệ thống có tài khoản người dùng hay không.
"""

from __future__ import annotations

import hmac
from hashlib import sha256


def verify_webhook_signature(
    body: bytes,
    signature_header: str | None,
    secret: str,
) -> bool:
    """
    Verify HMAC-SHA256 signature từ ChirpStack / LPWAN webhook.

    Header format: "sha256=<hex>"
    Constant-time compare để chống timing attack.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    provided = signature_header.removeprefix("sha256=")
    expected = hmac.new(secret.encode(), body, sha256).hexdigest()
    return hmac.compare_digest(provided, expected)
