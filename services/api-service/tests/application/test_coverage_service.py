"""CoverageQueryService.predict — orchestration tests.

Theo unit-test-guide.md §3 Tactic 4: Result branches kiểm bằng is_err/value,
KHÔNG dùng pytest.raises (Err không phải exception).
"""

from __future__ import annotations

from lora_coverage_api.application.coverage_service import CoverageQueryService
from lora_coverage_api.domain.errors import PredictionErrorCode
from lora_coverage_api.domain.result import Err, Ok

from ..factories import make_gateway, make_gateway_id, make_target
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
    gw_weak = make_gateway(gateway_id=make_gateway_id(seed=1), code="GW-WEAK")
    gw_strong = make_gateway(gateway_id=make_gateway_id(seed=2), code="GW-STRONG")
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
