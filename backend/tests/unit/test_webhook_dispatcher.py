"""
tests/unit/test_webhook_dispatcher.py — Unit test cho services.webhook_dispatcher.

Test pure helper functions (không chạm DB, không gọi network thật).
Mock httpx + DB session khi test fire_event/retry sẽ phức tạp →
tập trung test logic backoff schedule + sign helper là đủ.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.webhook_dispatcher import (
    MAX_ATTEMPTS,
    RETRY_DELAYS_SEC,
    _next_retry_at,
    _sign,
)


def test_sign_same_input_returns_deterministic_signature():
    # Arrange
    secret = "abc"
    body   = b"hello"

    # Act
    sig1 = _sign(secret, body)
    sig2 = _sign(secret, body)

    # Assert — HMAC deterministic + format chuẩn
    assert sig1 == sig2
    assert sig1.startswith("sha256=")


def test_next_retry_at_first_attempt_schedules_with_first_backoff_delay():
    # Arrange — vừa fail attempt #1
    before = datetime.now(timezone.utc)

    # Act
    next_time = _next_retry_at(attempt_no=1)

    # Assert — schedule khoảng RETRY_DELAYS_SEC[0] = 30s sau
    delta = (next_time - before).total_seconds()
    assert RETRY_DELAYS_SEC[0] - 1 <= delta <= RETRY_DELAYS_SEC[0] + 1


def test_next_retry_at_max_attempts_returns_none_to_signal_giveup():
    # Arrange + Act
    next_time = _next_retry_at(attempt_no=MAX_ATTEMPTS)

    # Assert — None = không retry nữa
    assert next_time is None