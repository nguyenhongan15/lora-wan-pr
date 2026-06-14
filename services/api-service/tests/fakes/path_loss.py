"""Predictable PathLossModel fake.

Stage1 thật là ITU-R P.1812 + P.2108 (cần DEM + crc-covlib) — không phù hợp
cho unit test CoverageQueryService. Fake này map gateway_id → rssi_dbm cố định,
không phụ thuộc geometry, không cần backend.
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
        # Direction-agnostic fake: UL = DL = injected RSSI. Margin tính so với
        # sensitivity chuẩn -120 dBm để CoverageQueryService.predict() (chọn
        # gateway theo min(UL, DL) margin) vẫn rank đúng theo rssi_for injection.
        margin = rssi - (-120.0)
        return Prediction(
            rssi_dbm=rssi,
            snr_db=snr,
            coverage_status=status,
            serving_gateway_id=gateway.id,
            confidence=Confidence(score=0.5, method=ConfidenceMethod.PHYSICS),
            model_version=self.model_version,
            recommended_sf=target.spreading_factor,
            uplink_rssi_dbm=rssi,
            uplink_snr_db=snr,
            uplink_margin_db=margin,
            uplink_status=status,
            downlink_rssi_dbm=rssi,
            downlink_snr_db=snr,
            downlink_margin_db=margin,
            downlink_status=status,
        )
