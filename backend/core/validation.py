"""
core/validation.py — Uniform missing-data scaffolding.

Phase v3.2 step 1. Thiết kế dựa trên philosophy_of_software_design — "Define
errors out of existence": thay vì để mỗi service tự `if x is None: raise ...`
với message khác nhau, gom về 1 helper.

Khi nào dùng:
  - Service đọc DB row, sắp dùng 1 cột nullable cho phép tính (vd
    gateway.tx_power_dbm cho path-loss). Nếu cột None → raise MissingFieldError
    để frontend hiển thị thông điệp tiếng Việt + actionable hint, KHÔNG crash 500.

Khi nào KHÔNG dùng:
  - Pydantic request body — đã có FastAPI 422 RequestValidationError.
  - Logic đơn giản None-check không liên quan DB (vd local var).

Ví dụ:
    from core.validation import require_field

    gw = await fetch_gateway(...)
    tx  = require_field(gw, 'tx_power_dbm',
                        label='công suất phát',
                        entity=f"gateway '{gw['name']}'",
                        hint='Chọn model từ thư viện hoặc nhập tx_power_dbm.')
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.exceptions import MissingFieldError


def require_field(
    obj: Mapping[str, Any] | object,
    field: str,
    *,
    label:  str | None = None,
    entity: str | None = None,
    hint:   str | None = None,
) -> Any:
    """
    Trả `obj[field]` (hoặc `obj.field`) nếu non-None, ngược lại raise
    MissingFieldError với message tiếng Việt.

    Args:
        obj:    Mapping (dict / Row) hoặc object có attribute.
        field:  Tên cột/attribute cần check.
        label:  Vietnamese label cho user (vd "công suất phát"). Default = field name.
        entity: Context object (vd "gateway 'GW-Central'") — giúp user biết row nào.
        hint:   Actionable hint (vd "Chọn model từ thư viện").

    Returns:
        Giá trị non-None.

    Raises:
        MissingFieldError (HTTP 422, code=MISSING_FIELD).
    """
    value = (
        obj.get(field) if isinstance(obj, Mapping)
        else getattr(obj, field, None)
    )
    if value is not None:
        return value

    label_vi = label or field
    ctx_vi   = f" của {entity}" if entity else ""
    msg      = f"Thiếu {label_vi}{ctx_vi}."
    if hint:
        msg += f" {hint}"

    raise MissingFieldError(
        message=msg,
        details=[{
            "field":  field,
            "label":  label_vi,
            "entity": entity,
            "hint":   hint,
        }],
    )
