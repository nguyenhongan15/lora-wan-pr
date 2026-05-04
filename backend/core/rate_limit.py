"""
core/rate_limit.py — Rate limiting đơn giản in-memory theo IP.

Cho production dùng Redis-backed để share across multiple workers,
nhưng với 1-2 uvicorn worker + nội bộ thì in-memory đủ.

Dùng Sliding Window đếm request per IP+endpoint trong N giây.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request

from core.exceptions import RateLimitedError


class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests   = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        """Raise RateLimitedError nếu vượt ngưỡng."""
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            bucket = self._buckets[key]
            # Xoá timestamp cũ
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self.max_requests:
                retry_after = int(self.window_seconds - (now - bucket[0])) + 1
                raise RateLimitedError(
                    f"Quá nhiều request. Thử lại sau {retry_after}s.",
                    details=[{"retry_after_seconds": retry_after}],
                )

            bucket.append(now)


# ── Pre-configured limiters ──────────────────────────────────────────────────
# (Tuning các giá trị này theo traffic thực tế)

_train_limiter = SlidingWindowLimiter(max_requests=5,  window_seconds=60)   # Train nặng
_sync_limiter  = SlidingWindowLimiter(max_requests=30, window_seconds=60)   # Sync vừa phải
_default_limit = SlidingWindowLimiter(max_requests=120, window_seconds=60)  # Default


def _client_ip(request: Request) -> str:
    # Ưu tiên X-Forwarded-For khi chạy sau proxy/load balancer
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_default(request: Request) -> None:
    _default_limit.check(f"default:{_client_ip(request)}")


def rate_limit_train(request: Request) -> None:
    _train_limiter.check(f"train:{_client_ip(request)}")


def rate_limit_sync(request: Request) -> None:
    _sync_limiter.check(f"sync:{_client_ip(request)}")
