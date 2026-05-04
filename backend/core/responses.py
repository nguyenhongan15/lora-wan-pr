"""
core/responses.py — Chuẩn hoá response wrapper theo API Contract.

Success:
  {
    "success": true,
    "data": { ... },
    "meta": { "page": 1, "limit": 20, "total": 100 }   // optional
  }

Error:
  {
    "success": false,
    "error": {
      "code": "USER_NOT_FOUND",
      "message": "Không tìm thấy người dùng.",
      "details": []
    }
  }
"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

T = TypeVar("T")


# ── Base model với camelCase alias tự động ──────────────────────────────────

class CamelModel(BaseModel):
    """
    Mọi response schema nên kế thừa class này để tự động
    chuyển snake_case Python → camelCase JSON.

    Ví dụ: field `gateway_eui` sẽ serialize ra `gatewayEui`.
    """
    model_config = ConfigDict(
        alias_generator  = to_camel,
        populate_by_name = True,
        from_attributes  = True,
    )


# ── Wrapper schemas ──────────────────────────────────────────────────────────

class Meta(CamelModel):
    page:  Optional[int] = None
    limit: Optional[int] = None
    total: Optional[int] = None


class ErrorDetail(CamelModel):
    code:    str                       # stringly-typed để FE map i18n
    message: str
    details: list[Any] = []


class SuccessResponse(CamelModel, Generic[T]):
    success: bool                 = True
    data:    Optional[T]          = None
    meta:    Optional[Meta]       = None


class ErrorResponse(CamelModel):
    success: bool         = False
    error:   ErrorDetail


# ── Helper functions ─────────────────────────────────────────────────────────

def ok(data: Any = None, meta: dict | None = None) -> dict:
    """Tạo response thành công."""
    body: dict = {"success": True, "data": data}
    if meta is not None:
        body["meta"] = meta
    return body


def fail(code: str, message: str, details: list | None = None) -> dict:
    """Tạo response lỗi."""
    return {
        "success": False,
        "error": {
            "code":    code,
            "message": message,
            "details": details or [],
        },
    }
