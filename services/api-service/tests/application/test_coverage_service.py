"""CoverageQueryService.predict — orchestration tests.

Theo unit-test-guide.md §3 Tactic 4: Result branches kiểm bằng is_err/value,
KHÔNG dùng pytest.raises (Err không phải exception).
"""

from __future__ import annotations

from lora_coverage_api.application.coverage_service import CoverageQueryService
from lora_coverage_api.domain.errors import PredictionErrorCode
from lora_coverage_api.domain.result import Err, Ok

from ..factories import (
    DA_NANG_LAT,
    DA_NANG_LNG,
    make_gateway,
    make_gateway_id,
    make_target,
)
from ..fakes.gateway_directory import FakeGatewayDirectory
from ..fakes.path_loss import FakePathLossModel


def test_predict_returns_err_no_gateway_nearby_when_directory_empty():
    service = CoverageQueryService(directory=FakeGatewayDirectory(), model=FakePathLossModel())

    result = service.predict(make_target())

    assert isinstance(result, Err)
    assert result.error.code == PredictionErrorCode.NO_GATEWAY_NEARBY


def test_predict_returns_ok_prediction_when_one_gateway_in_range():
    gw = make_gateway()
    service = CoverageQueryService(directory=FakeGatewayDirectory([gw]), model=FakePathLossModel())

    result = service.predict(make_target())

    assert isinstance(result, Ok)
    assert result.value.serving_gateway_id == gw.id


def test_predict_picks_gateway_with_highest_rssi_when_multiple_candidates():
    # Hai site KHÁC vị trí (>80m) để không bị gộp dedup — test rank theo RSSI.
    gw_weak = make_gateway(gateway_id=make_gateway_id(seed=1), code="GW-WEAK")
    gw_strong = make_gateway(
        gateway_id=make_gateway_id(seed=2), code="GW-STRONG", longitude=DA_NANG_LNG + 0.02
    )
    model = FakePathLossModel(default_rssi_dbm=-110.0)
    model.rssi_for[gw_weak.id] = -110.0
    model.rssi_for[gw_strong.id] = -80.0
    service = CoverageQueryService(
        directory=FakeGatewayDirectory([gw_weak, gw_strong]), model=model
    )

    result = service.predict(make_target())

    assert isinstance(result, Ok)
    assert result.value.serving_gateway_id == gw_strong.id
    assert result.value.rssi_dbm == -80.0


def test_predict_returns_err_when_only_gateways_are_outside_30km():
    # Gateway ở Hà Nội (~620km từ Đà Nẵng) — ngoài 30km radius
    far_gw = make_gateway(latitude=21.0285, longitude=105.8542)
    service = CoverageQueryService(
        directory=FakeGatewayDirectory([far_gw]), model=FakePathLossModel()
    )

    result = service.predict(make_target())

    assert isinstance(result, Err)
    assert result.error.code == PredictionErrorCode.NO_GATEWAY_NEARBY


def test_predict_carries_model_version_from_path_loss_model():
    gw = make_gateway()
    service = CoverageQueryService(directory=FakeGatewayDirectory([gw]), model=FakePathLossModel())

    result = service.predict(make_target())

    assert isinstance(result, Ok)
    assert result.value.model_version == "fake-test-v0"


def test_predict_picks_gateway_by_min_uplink_downlink_margin_not_top_level_rssi():
    """Bidirectional select: gateway thắng theo bottleneck margin = min(UL,DL).

    FakePathLossModel set UL=DL=injected RSSI nên test này bằng đẳng cấp với
    rank-by-RSSI. Mở rộng fake để asymmetric khi cần test edge case khác.
    """
    # Hai site KHÁC vị trí (>80m) để không bị gộp dedup.
    gw_high_rssi = make_gateway(gateway_id=make_gateway_id(seed=1), code="GW-HIGH")
    gw_low_rssi = make_gateway(
        gateway_id=make_gateway_id(seed=2), code="GW-LOW", longitude=DA_NANG_LNG + 0.02
    )
    model = FakePathLossModel(default_rssi_dbm=-100.0)
    model.rssi_for[gw_high_rssi.id] = -85.0  # margin = 35 dB
    model.rssi_for[gw_low_rssi.id] = -110.0  # margin = 10 dB
    service = CoverageQueryService(
        directory=FakeGatewayDirectory([gw_high_rssi, gw_low_rssi]), model=model
    )

    result = service.predict(make_target())

    assert isinstance(result, Ok)
    assert result.value.serving_gateway_id == gw_high_rssi.id
    # min(UL,DL) margin của winner phải > của loser
    assert min(result.value.uplink_margin_db, result.value.downlink_margin_db) == 35.0


def test_predict_dedupes_colocated_gateways_into_one_site():
    """Hai gateway TRÙNG tọa độ (khác id/code/anten) → gộp thành 1 site.

    Đại diện = anten cao nhất (không phải RSSI mạnh nhất): chứng minh dedup chạy
    trước vòng chọn. covering_gateway_count đếm theo site = 1, không phải 2 radio.
    """
    twin_low_ant = make_gateway(
        gateway_id=make_gateway_id(seed=1),
        code="TWIN-LOWANT",
        latitude=DA_NANG_LAT,
        longitude=DA_NANG_LNG,
        antenna_height_m=15.0,
    )
    twin_high_ant = make_gateway(
        gateway_id=make_gateway_id(seed=2),
        code="TWIN-HIGHANT",
        latitude=DA_NANG_LAT,
        longitude=DA_NANG_LNG,
        antenna_height_m=40.0,
    )
    # Twin anten thấp lại có RSSI mạnh hơn — nếu KHÔNG dedup, nó sẽ thắng theo
    # margin. Dedup giữ đại diện anten cao → twin_high_ant thắng.
    model = FakePathLossModel(default_rssi_dbm=-95.0)
    model.rssi_for[twin_low_ant.id] = -80.0
    model.rssi_for[twin_high_ant.id] = -95.0
    service = CoverageQueryService(
        directory=FakeGatewayDirectory([twin_low_ant, twin_high_ant]), model=model
    )

    result = service.predict(make_target())

    assert isinstance(result, Ok)
    assert result.value.serving_gateway_id == twin_high_ant.id
    assert result.value.covering_gateway_count == 1


def test_predict_does_not_merge_distinct_sites():
    """Hai site cách xa (>80m) KHÔNG bị gộp — đếm redundancy đúng 2."""
    gw_a = make_gateway(gateway_id=make_gateway_id(seed=1), code="SITE-A")
    gw_b = make_gateway(
        gateway_id=make_gateway_id(seed=2), code="SITE-B", longitude=DA_NANG_LNG + 0.02
    )
    model = FakePathLossModel(default_rssi_dbm=-90.0)  # cả 2 đều STRONG
    service = CoverageQueryService(directory=FakeGatewayDirectory([gw_a, gw_b]), model=model)

    result = service.predict(make_target())

    assert isinstance(result, Ok)
    assert result.value.covering_gateway_count == 2
