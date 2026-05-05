"""Predictable PathLossModel fake.

Stage1 thật là phép log-distance — tốt cho test path_loss riêng nhưng
khi test CoverageQueryService ta cần kiểm soát "gateway nào là best".
Fake này map gateway_id → rssi_dbm cố định, không phụ thuộc geometry.
"""

from __future__ import annotations

from lora_coverage_api.domain.coverage import (
    Confidence,
    ConfidenceMethod,
    CoverageStatus,
    Gateway,
    Prediction,
    Target,
)


class FakePathLossModel:
    """RSSI per gateway được test inject trực tiếp.

    Default RSSI = -90 dBm. Override qua `rssi_for[gateway_id] = value`.
    """

    model_version = "fake-test-v0"

    def __init__(self, default_rssi_dbm: float = -90.0) -> None:
        self.default_rssi_dbm = default_rssi_dbm
        self.rssi_for: dict = {}  # GatewayId → float

    def predict(self, target: Target, gateway: Gateway) -> Prediction:
        rssi = self.rssi_for.get(gateway.id, self.default_rssi_dbm)
        snr = rssi - (-117.0)  # crude noise floor cho test purposes
        status = CoverageStatus.STRONG if rssi >= -100 else CoverageStatus.WEAK
        return Prediction(
            rssi_dbm=rssi,
            snr_db=snr,
            coverage_status=status,
            serving_gateway_id=gateway.id,
            confidence=Confidence(score=0.5, method=ConfidenceMethod.EMPIRICAL),
            model_version=self.model_version,
        )
