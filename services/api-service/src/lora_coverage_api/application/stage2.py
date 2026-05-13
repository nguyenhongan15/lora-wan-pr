"""Stage 2 capability interface (dependency inversion).

application/ depends on this Protocol, not the concrete HTTP client. Layer
contract: application MUST NOT import infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain.coverage import Gateway, Target


@dataclass(frozen=True, slots=True)
class Stage2Result:
    """Output Stage 2 — residual dB + model_version cho audit trail."""

    residual_db: float
    model_version: str


class Stage2Predictor(Protocol):
    """Capability: refine Stage 1 RSSI bằng residual model.

    Return None khi không có active model hoặc transient failure — caller
    fallback Stage 1 nguyên trạng.
    """

    async def predict_residual(self, target: Target, gateway: Gateway) -> Stage2Result | None: ...
