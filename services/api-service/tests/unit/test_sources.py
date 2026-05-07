"""Sources interface contract + registry."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from lora_coverage_api.application.sources import (
    DataSource,
    GatewayRecord,
    MeasurementRecord,
    SourceAuthError,
    UnknownSourceTypeError,
    get_adapter,
    known_source_types,
    register,
)
from lora_coverage_api.application.sources.registry import _REGISTRY
from tests.fakes.data_source import FakeDataSource


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Mỗi test bắt đầu với registry rỗng, không leak giữa tests."""
    saved = dict(_REGISTRY)
    _REGISTRY.clear()
    yield
    _REGISTRY.clear()
    _REGISTRY.update(saved)


def _gw(eid: str = "gw-1") -> GatewayRecord:
    return GatewayRecord(
        external_id=eid, latitude=16.0, longitude=108.0, altitude_m=10.0, label="x"
    )


def _meas(eid: str, t: datetime) -> MeasurementRecord:
    return MeasurementRecord(
        external_id=eid,
        time=t,
        latitude=16.0,
        longitude=108.0,
        rssi_dbm=-95.0,
        snr_db=5.0,
        spreading_factor=7,
        frequency_mhz=868.0,
        device_external_id="dev-A",
        serving_gateway_external_id=None,
    )


class TestRecords:
    def test_records_are_frozen(self):
        gw = _gw()
        with pytest.raises(FrozenInstanceError):
            gw.external_id = "x"  # type: ignore[misc]


class TestDataSourceContract:
    def test_abc_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            DataSource()  # type: ignore[abstract]

    def test_fake_implements_full_contract(self):
        src = FakeDataSource(gateways=[_gw("a"), _gw("b")])
        handle = src.connect({"email": "x", "password": "y"})
        assert handle["token"] == "fake-token"
        assert [g.external_id for g in src.fetch_gateways(handle)] == ["a", "b"]

    def test_connect_rejects_empty_creds(self):
        src = FakeDataSource()
        with pytest.raises(SourceAuthError):
            src.connect({})

    def test_fetch_measurements_filters_since(self):
        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        t2 = datetime(2026, 2, 1, tzinfo=UTC)
        src = FakeDataSource(measurements=[_meas("m1", t1), _meas("m2", t2)])
        handle = src.connect({"k": "v"})
        out = list(src.fetch_measurements(handle, since=t1))
        assert [m.external_id for m in out] == ["m2"]

    def test_fetch_measurements_none_since_yields_all(self):
        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        src = FakeDataSource(measurements=[_meas("m1", t1)])
        handle = src.connect({"k": "v"})
        assert len(list(src.fetch_measurements(handle, since=None))) == 1


class TestRegistry:
    def test_register_and_get(self):
        register("fake", FakeDataSource)
        adapter = get_adapter("fake")
        assert isinstance(adapter, FakeDataSource)

    def test_get_unknown_raises(self):
        with pytest.raises(UnknownSourceTypeError) as ei:
            get_adapter("nonexistent")
        assert ei.value.http_status == 400
        assert ei.value.code == "unknown_source_type"

    def test_known_source_types_lists_registered(self):
        register("fake", FakeDataSource)
        assert "fake" in known_source_types()

    def test_register_is_idempotent(self):
        register("fake", FakeDataSource)
        register("fake", FakeDataSource)
        assert known_source_types().count("fake") == 1
