"""Value-object builders cho tests.

Defaults là valid + boring. Test bodies override chỉ field cần test.
Theo unit-test-guide.md §2 Principle 2: pull complexity vào fixtures/factories.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from lora_coverage_api.domain.coverage import (
    Confidence,
    ConfidenceMethod,
    CoverageStatus,
    Gateway,
    GatewayId,
    LinkBottleneck,
    Prediction,
    Target,
)
from lora_coverage_api.domain.survey import (
    SurveyBatch,
    SurveyRecord,
    UploaderId,
)

# Đà Nẵng centre — dùng làm defaults cho mọi factory geographic.
DA_NANG_LAT = 16.0544
DA_NANG_LNG = 108.2022


def make_gateway_id(seed: int = 1) -> GatewayId:
    """Deterministic GatewayId, uuid5 cho repeatable tests."""
    import uuid

    namespace = uuid.UUID("11111111-1111-1111-1111-111111111111")
    return GatewayId(uuid.uuid5(namespace, f"gw-{seed}"))


def make_gateway(
    *,
    gateway_id: GatewayId | None = None,
    code: str = "DAD-001",
    name: str = "Test Gateway Đà Nẵng",
    latitude: float = DA_NANG_LAT,
    longitude: float = DA_NANG_LNG,
    altitude_m: float = 10.0,
    antenna_height_m: float = 15.0,
    antenna_gain_dbi: float = 2.0,
    tx_power_dbm: float = 14.0,
    frequency_mhz: float = 923.0,
    rx_antenna_gain_dbi: float | None = None,
    rx_sensitivity_dbm: float | None = None,
) -> Gateway:
    return Gateway(
        id=gateway_id or make_gateway_id(),
        code=code,
        name=name,
        latitude=latitude,
        longitude=longitude,
        altitude_m=altitude_m,
        antenna_height_m=antenna_height_m,
        antenna_gain_dbi=antenna_gain_dbi,
        tx_power_dbm=tx_power_dbm,
        frequency_mhz=frequency_mhz,
        rx_antenna_gain_dbi=rx_antenna_gain_dbi,
        rx_sensitivity_dbm=rx_sensitivity_dbm,
    )


def make_target(
    *,
    latitude: float = DA_NANG_LAT,
    longitude: float = DA_NANG_LNG,
    spreading_factor: int = 7,
    frequency_mhz: float = 923.0,
    tx_power_dbm: float = 14.0,
    tx_antenna_gain_dbi: float = 2.0,
    rx_antenna_gain_dbi: float = 0.0,
    rx_sensitivity_dbm: float | None = None,
) -> Target:
    return Target(
        latitude=latitude,
        longitude=longitude,
        spreading_factor=spreading_factor,
        frequency_mhz=frequency_mhz,
        tx_power_dbm=tx_power_dbm,
        tx_antenna_gain_dbi=tx_antenna_gain_dbi,
        rx_antenna_gain_dbi=rx_antenna_gain_dbi,
        rx_sensitivity_dbm=rx_sensitivity_dbm,
    )


def make_prediction(
    *,
    rssi_dbm: float = -90.0,
    snr_db: float = 10.0,
    coverage_status: CoverageStatus = CoverageStatus.STRONG,
    serving_gateway_id: GatewayId | None = None,
    confidence_score: float = 0.85,
    confidence_method: ConfidenceMethod = ConfidenceMethod.EMPIRICAL,
    model_version: str = "stage1-test-v0",
    recommended_sf: int = 7,
    uplink_rssi_dbm: float | None = None,
    uplink_snr_db: float | None = None,
    uplink_margin_db: float = 30.0,
    uplink_status: CoverageStatus | None = None,
    downlink_rssi_dbm: float | None = None,
    downlink_snr_db: float | None = None,
    downlink_margin_db: float = 30.0,
    downlink_status: CoverageStatus | None = None,
    bottleneck: LinkBottleneck = "both_ok",
) -> Prediction:
    """Defaults: UL = DL = top-level rssi/snr/status. Bottleneck "both_ok".

    Test bodies test bidirectional behavior override UL/DL/bottleneck explicit;
    legacy tests chỉ assert top-level fields không cần đụng.
    """
    return Prediction(
        rssi_dbm=rssi_dbm,
        snr_db=snr_db,
        coverage_status=coverage_status,
        serving_gateway_id=serving_gateway_id or make_gateway_id(),
        confidence=Confidence(score=confidence_score, method=confidence_method),
        model_version=model_version,
        recommended_sf=recommended_sf,
        uplink_rssi_dbm=rssi_dbm if uplink_rssi_dbm is None else uplink_rssi_dbm,
        uplink_snr_db=snr_db if uplink_snr_db is None else uplink_snr_db,
        uplink_margin_db=uplink_margin_db,
        uplink_status=coverage_status if uplink_status is None else uplink_status,
        downlink_rssi_dbm=rssi_dbm if downlink_rssi_dbm is None else downlink_rssi_dbm,
        downlink_snr_db=snr_db if downlink_snr_db is None else downlink_snr_db,
        downlink_margin_db=downlink_margin_db,
        downlink_status=coverage_status if downlink_status is None else downlink_status,
        bottleneck=bottleneck,
    )


def make_survey_record(
    *,
    timestamp: datetime | None = None,
    latitude: float = DA_NANG_LAT,
    longitude: float = DA_NANG_LNG,
    rssi_dbm: float = -95.0,
    snr_db: float = 7.5,
    spreading_factor: int = 7,
    frequency_mhz: float = 923.0,
    device_id: str | None = "test-device-001",
    serving_gateway_id: GatewayId | None = None,
) -> SurveyRecord:
    return SurveyRecord(
        timestamp=timestamp or datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        latitude=latitude,
        longitude=longitude,
        rssi_dbm=rssi_dbm,
        snr_db=snr_db,
        spreading_factor=spreading_factor,
        frequency_mhz=frequency_mhz,
        device_id=device_id,
        serving_gateway_id=serving_gateway_id,
    )


def make_uploader_id(seed: int = 1) -> UploaderId:
    import uuid

    namespace = uuid.UUID("22222222-2222-2222-2222-222222222222")
    return UploaderId(uuid.uuid5(namespace, f"uploader-{seed}"))


def make_survey_batch(
    *,
    uploader_id: UploaderId | None = None,
    records: Sequence[SurveyRecord] | None = None,
    n_records: int = 3,
) -> SurveyBatch:
    """Defaults: N valid records ở Đà Nẵng, varying RSSI quanh -95dBm."""
    if records is None:
        records = [
            make_survey_record(rssi_dbm=-90.0 - i, device_id=f"dev-{i:03d}")
            for i in range(n_records)
        ]
    return SurveyBatch(
        uploader_id=uploader_id or make_uploader_id(),
        records=records,
    )
