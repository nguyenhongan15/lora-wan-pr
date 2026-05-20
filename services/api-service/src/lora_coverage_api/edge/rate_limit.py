"""Rate-limit primitives — distributed counter via Valkey/Redis.

Architecture (Chapter 4 — "Design a Rate Limiter"):

    Client ─→ Rate limiter middleware ─→ API workers
                       │
                       └──→ Cache (Valkey) ← shared counter store

Worker per-process in-memory storage không sync giữa N workers → effective
rate-limit = (N * ngưỡng config). Centralized data store fix root cause:
mọi worker SET/GET counter cùng 1 Valkey key, atomic operations đảm bảo
correctness dưới race condition (chapter §Distributed Environments).

Algorithm: `moving-window` (Chapter §3.4 "Sliding Window Log"). Accuracy
ưu tiên hơn memory vì auth endpoint volume thấp (< 100 rps total); fixed-window
có edge-spike issue khi bot bắn double quota quanh window boundary (§3.3
"Fixed Window Issue").

Fallback in-memory cho dev (RATE_LIMIT_STORAGE_URI rỗng) — production-mode
config validator (`_rate_limit_storage_required_in_prod`) chặn empty từ
startup, không thể vô tình deploy với storage rỗng.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from ..config import get_settings

_settings = get_settings()

# storage_uri="" (default) → slowapi tự fallback `memory://`. Production có
# validator chặn nên không lo silent in-memory ở prod.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_settings.rate_limit_storage_uri or "memory://",
    strategy="moving-window",
)
