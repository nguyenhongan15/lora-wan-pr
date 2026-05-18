"""Out-Of-Domain detector — bounding-box check trên feature vector tại serving time.

What:
  OODDetector.check(feature_vector) → OODResult(is_ood, violating_features).
Hidden:
  Per-feature bound từ meta.json (min/max numeric, value-set categorical).
  Sample OOD nếu ≥ 1 feature ngoài bound.
Failure mode:
  Feature thiếu trong bounds dict → skip (assume in-domain). Log warning lần
  load, không raise per-request.

Lý do bounding-box thay vì Mahalanobis / IF / kNN:
  - Bounds train-time được lưu thẳng vào meta.json (~1 KB) — không cần extra
    artifact. Load O(n_features), check O(n_features) — không impact P99 latency.
  - Per-feature interpretable: log "distance>OOD_max" để debug dễ hơn
    "Mahalanobis score>χ²".
  - Đủ cho rào chắn cấp 1; combo với physics guardrail (training/guardrail.py)
    là 2 lớp độc lập.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..features.extractor import FeatureVector

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OODResult:
    """1 sample check kết quả.

    `violating_features` non-empty ⇔ is_ood = True. Caller log + chọn fallback.
    """

    is_ood: bool
    violating_features: tuple[str, ...]


class OODDetector:
    """Per-feature bound check. Stateless sau construct, thread-safe."""

    def __init__(self, bounds: dict[str, dict[str, Any]]) -> None:
        """Build từ meta.json["feature_bounds"].

        Args:
            bounds: {col: {"min", "max"} numeric | {"values": [...]} categorical}.
        """
        self._numeric: dict[str, tuple[float, float]] = {}
        self._categorical: dict[str, set[Any]] = {}
        for col, spec in bounds.items():
            if "min" in spec and "max" in spec:
                self._numeric[col] = (float(spec["min"]), float(spec["max"]))
            elif "values" in spec:
                self._categorical[col] = set(spec["values"])
            else:
                log.warning("OOD bounds for %s has unknown schema; skip", col)
        log.info(
            "OODDetector built: %d numeric, %d categorical",
            len(self._numeric),
            len(self._categorical),
        )

    def check(self, fv: FeatureVector) -> OODResult:
        """1 FeatureVector → OODResult.

        Numeric: outside [min, max] → violate.
        Categorical: not in known value set → violate.
        Missing feature: skip (in-domain assumption).
        """
        violations: list[str] = []
        # FeatureVector slots — chuyển sang dict để truy cập theo tên cột.
        # __dict__ không có vì frozen + slots, dùng getattr.
        for col, (lo, hi) in self._numeric.items():
            v = getattr(fv, col, None)
            if v is None:
                continue
            if not (lo <= float(v) <= hi):
                violations.append(col)
        for col, values in self._categorical.items():
            v = getattr(fv, col, None)
            if v is None:
                continue
            # spreading_factor int vs categorical list int — direct compare OK.
            # serving_gateway_id str vs str — OK.
            if v not in values:
                violations.append(col)
        return OODResult(is_ood=bool(violations), violating_features=tuple(violations))
