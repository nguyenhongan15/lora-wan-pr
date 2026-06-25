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
    """Output Stage 2.

    `residual_db` = (ET end-to-end RSSI prediction) - (Stage 1 RSSI). Tên field
    giữ "residual" cho ổn định contract; ý nghĩa toán học hiện là "delta để
    chuyển từ baseline Stage 1 sang dự đoán ML end-to-end".
    """

    residual_db: float
    model_version: str
    # MSE holdout (dB²) của ML model — None nếu ml-service không cung cấp. Dùng
    # để dựng epistemic variance cho confidence (dải ±σ trung thực trên UI).
    holdout_mse_db2: float | None = None


class Stage2Predictor(Protocol):
    """Capability: tinh chỉnh Stage 1 RSSI bằng dự đoán ML end-to-end.

    Return None khi không có active model hoặc transient failure — caller
    fallback Stage 1 nguyên trạng.

    `stage1_rssi_dbm`: Stage 1 RSSI (dBm) caller đã tính. ml-service Extra
    Trees train trên RSSI tuyệt đối; phải biết baseline Stage 1 để trả delta.
    """

    async def predict_residual(
        self, target: Target, gateway: Gateway, stage1_rssi_dbm: float
    ) -> Stage2Result | None: ...
