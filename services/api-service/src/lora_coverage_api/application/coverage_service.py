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

        # Predict trên mọi candidate, lấy RSSI cao nhất làm serving.
        best: Prediction | None = None
        for gw in candidates:
            p = self._model.predict(target, gw)
            if best is None or p.rssi_dbm > best.rssi_dbm:
                best = p

        assert best is not None  # candidates không rỗng → best có giá trị
        return Ok(best)
