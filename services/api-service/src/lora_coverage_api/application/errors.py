"""Application-layer error hierarchy root.

Plan-auth-v1 §8.1: 1 cây ApplicationError + 1 handler ở edge layer. Subclass
override `http_status` và `code` (snake_case). Edge dispatcher convert thành
RFC 7807 response không cần biết chi tiết.

Không kế thừa từ HTTPException — application layer KHÔNG phụ thuộc framework
HTTP. Edge layer adapt.
"""

from __future__ import annotations


class ApplicationError(Exception):
    http_status: int = 500
    code: str = "internal_error"
