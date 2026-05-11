"""CoverageQuery use case (application layer).

Chọn serving gateway tốt nhất từ danh sách candidates rồi predict.
Phụ thuộc 2 thứ qua DI: GatewayDirectory + PathLossModel.
"""

from __future__ import annotations

from ..domain.coverage import Prediction, Target
from ..domain.errors import PredictionErrorCode, PredictionUnavailable
from ..domain.result import Err, Ok, Result
from .path_loss import PathLossModel
from .repositories import GatewayDirectory


class CoverageQueryService:
    def __init__(self, directory: GatewayDirectory, model: PathLossModel) -> None:
        self._directory = directory
        self._model = model

    def predict(self, target: Target) -> Result[Prediction, PredictionUnavailable]:
        candidates = self._directory.find_serving_candidates(target)
        if not candidates:
            return Err(
                PredictionUnavailable(
                    code=PredictionErrorCode.NO_GATEWAY_NEARBY,
                    message="Không có gateway nào trong bán kính 30km.",
                )
            )

        # Predict trên mọi candidate, chọn gateway có bottleneck margin lớn
        # nhất (= min(UL margin, DL margin)). Bottleneck-aware vì link 2 chiều
        # phải đảm bảo: 1 GW có DL strong nhưng UL chết do RX gain thấp sẽ
        # KHÔNG phục vụ được — chọn theo top-level rssi_dbm (DL only) sẽ
        # bias sai. Behavioral change so với v0 chỉ-DL.
        best: Prediction | None = None
        best_margin: float = float("-inf")
        for gw in candidates:
            p = self._model.predict(target, gw)
            margin = min(p.uplink_margin_db, p.downlink_margin_db)
            if margin > best_margin:
                best = p
                best_margin = margin

        assert best is not None  # candidates không rỗng → best có giá trị
        return Ok(best)
