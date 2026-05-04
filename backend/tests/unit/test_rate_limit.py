"""
tests/unit/test_rate_limit.py — Unit test cho core.rate_limit.SlidingWindowLimiter.

Mỗi test khởi tạo limiter mới (đảm bảo Independent — F.I.R.S.T).
"""

from __future__ import annotations

import pytest

from core.exceptions import RateLimitedError
from core.rate_limit import SlidingWindowLimiter


def test_check_under_threshold_does_not_raise():
    # Arrange — limit 3 req / 60s
    limiter = SlidingWindowLimiter(max_requests=3, window_seconds=60)

    # Act + Assert — 3 lần gọi đầu phải pass
    limiter.check("ip-1")
    limiter.check("ip-1")
    limiter.check("ip-1")


def test_check_exceeds_threshold_raises_rate_limited_error():
    # Arrange
    limiter = SlidingWindowLimiter(max_requests=2, window_seconds=60)
    limiter.check("ip-1")
    limiter.check("ip-1")

    # Act + Assert — request thứ 3 phải bị reject
    with pytest.raises(RateLimitedError):
        limiter.check("ip-1")


def test_check_different_keys_isolated_independently():
    # Arrange — limit 1 req. ip-1 đã dùng hết quota.
    limiter = SlidingWindowLimiter(max_requests=1, window_seconds=60)
    limiter.check("ip-1")

    # Act + Assert — ip-2 vẫn còn quota riêng
    limiter.check("ip-2")