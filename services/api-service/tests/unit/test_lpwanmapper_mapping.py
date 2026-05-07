"""Unit test cho _mapping.py (pure functions, no HTTP).

Fixture shape modeled trên r-dt/response_*.json (real ChirpStack uplink capture).
"""

from __future__ import annotations

from datetime import UTC, datetime

from lora_coverage_api.application.sources.lpwanmapper._mapping import (
    gateway_record,
    measurement_records,
)


class TestGatewayRecord:
    def test_full_login_shape(self):
        raw = {"gatewayId": "gw-01", "latitude": 16.05, "longitude": 108.21, "altitude": 12.0}
        gw = gateway_record(raw)
        assert gw is not None
        assert (gw.external_id, gw.latitude, gw.longitude, gw.altitude_m) == (
            "gw-01",
            16.05,
            108.21,
            12.0,
        )
        assert gw.label is None  # /login không trả name

    def test_missing_id_returns_none(self):
        assert gateway_record({"latitude": 16.0, "longitude": 108.0}) is None

    def test_invalid_lat_returns_none(self):
        assert gateway_record({"gatewayId": "x", "latitude": "abc", "longitude": 108.0}) is None

    def test_altitude_optional(self):
        gw = gateway_record({"gatewayId": "g", "latitude": 16.0, "longitude": 108.0})
        assert gw is not None and gw.altitude_m is None


def _uplink(**overrides):
    """Realistic ChirpStack uplink fixture (single rxInfo entry).

    Matches shape của r-dt/response_1777987550466.json[i].
    GNSS lat/lon là scaled int (degree * 1e7).
    """
    base = {
        "_id": "u-1",
        "time": "2026-05-07T10:00:00Z",
        "deviceInfo": {"deviceName": "dev-A", "devEui": "0011223344556677"},
        "txInfo": {
            "frequency": 868_000_000,
            "modulation": {"lora": {"spreadingFactor": 7}},
        },
        "object": {
            "gnss_latitude": 160_000_000,  # 16.0°
            "gnss_longitude": 1_080_000_000,  # 108.0°
        },
        "rxInfo": [
            {"gatewayId": "gw-1", "rssi": -90, "snr": 5.5, "gwTime": "2026-05-07T10:00:01Z"},
        ],
    }
    base.update(overrides)
    return base


class TestMeasurementRecords:
    def test_full_single_rx(self):
        recs = list(measurement_records(_uplink()))
        assert len(recs) == 1
        m = recs[0]
        assert m.external_id == "u-1@gw-1"
        assert m.time == datetime(2026, 5, 7, 10, 0, 1, tzinfo=UTC)
        assert (m.latitude, m.longitude) == (16.0, 108.0)
        assert (m.rssi_dbm, m.snr_db) == (-90.0, 5.5)
        assert m.spreading_factor == 7
        assert m.frequency_mhz == 868.0
        assert m.device_external_id == "dev-A"
        assert m.serving_gateway_external_id == "gw-1"

    def test_multi_rx_emits_one_per_gateway(self):
        u = _uplink(
            rxInfo=[
                {"gatewayId": "gw-1", "rssi": -90, "snr": 5.0, "gwTime": "2026-05-07T10:00:01Z"},
                {"gatewayId": "gw-2", "rssi": -95, "snr": 3.0, "gwTime": "2026-05-07T10:00:01Z"},
                {"gatewayId": "gw-3", "rssi": -100, "snr": 1.0, "gwTime": "2026-05-07T10:00:01Z"},
            ]
        )
        recs = list(measurement_records(u))
        assert len(recs) == 3
        assert {r.serving_gateway_external_id for r in recs} == {"gw-1", "gw-2", "gw-3"}
        assert {r.external_id for r in recs} == {"u-1@gw-1", "u-1@gw-2", "u-1@gw-3"}

    def test_skip_rx_missing_rssi(self):
        u = _uplink(
            rxInfo=[
                {"gatewayId": "gw-1", "rssi": -90, "gwTime": "2026-05-07T10:00:01Z"},
                {"gatewayId": "gw-2", "gwTime": "2026-05-07T10:00:01Z"},  # no rssi → skip
            ]
        )
        recs = list(measurement_records(u))
        assert len(recs) == 1
        assert recs[0].serving_gateway_external_id == "gw-1"

    def test_skip_rx_missing_gateway_id(self):
        u = _uplink(rxInfo=[{"rssi": -90, "gwTime": "2026-05-07T10:00:01Z"}])
        assert list(measurement_records(u)) == []

    def test_no_device_returns_empty(self):
        u = _uplink(deviceInfo={})
        assert list(measurement_records(u)) == []

    def test_no_gnss_returns_empty(self):
        u = _uplink(object={})
        assert list(measurement_records(u)) == []

    def test_gnss_zero_treated_as_no_fix(self):
        u = _uplink(object={"gnss_latitude": 0, "gnss_longitude": 1_080_000_000})
        assert list(measurement_records(u)) == []

    def test_gnss_already_in_degrees(self):
        u = _uplink(object={"gnss_latitude": 16.05, "gnss_longitude": 108.21})
        recs = list(measurement_records(u))
        assert len(recs) == 1
        assert (recs[0].latitude, recs[0].longitude) == (16.05, 108.21)

    def test_gnss_out_of_range_skipped(self):
        # scaled lat = 9.5e8 → 95° (> 90)
        u = _uplink(object={"gnss_latitude": 950_000_000, "gnss_longitude": 1_080_000_000})
        assert list(measurement_records(u)) == []

    def test_freq_already_in_mhz(self):
        u = _uplink(txInfo={"frequency": 868.0, "modulation": {"lora": {"spreadingFactor": 7}}})
        recs = list(measurement_records(u))
        assert len(recs) == 1 and recs[0].frequency_mhz == 868.0

    def test_freq_missing_ok(self):
        u = _uplink(txInfo={"modulation": {"lora": {"spreadingFactor": 7}}})
        recs = list(measurement_records(u))
        assert len(recs) == 1 and recs[0].frequency_mhz is None

    def test_sf_missing_ok(self):
        u = _uplink(txInfo={"frequency": 868_000_000})
        recs = list(measurement_records(u))
        assert len(recs) == 1 and recs[0].spreading_factor is None

    def test_fallback_dedup_id_when_no_uplink_id(self):
        u = _uplink()
        del u["_id"]
        recs = list(measurement_records(u))
        assert len(recs) == 1
        assert "dev-A@" in recs[0].external_id
        assert "@gw-1" in recs[0].external_id

    def test_falls_back_to_dev_eui(self):
        u = _uplink(deviceInfo={"devEui": "AABBCCDD"})
        recs = list(measurement_records(u))
        assert len(recs) == 1 and recs[0].device_external_id == "AABBCCDD"

    def test_uplink_time_used_when_rx_missing_gwtime(self):
        u = _uplink(rxInfo=[{"gatewayId": "gw-1", "rssi": -90}])
        recs = list(measurement_records(u))
        assert len(recs) == 1
        assert recs[0].time == datetime(2026, 5, 7, 10, 0, tzinfo=UTC)

    def test_no_rx_returns_empty(self):
        u = _uplink(rxInfo=[])
        assert list(measurement_records(u)) == []

    def test_rxinfo_not_list_returns_empty(self):
        u = _uplink(rxInfo=None)
        assert list(measurement_records(u)) == []

    def test_epoch_seconds_time(self):
        u = _uplink(rxInfo=[{"gatewayId": "gw-1", "rssi": -90, "gwTime": 1762509600}])
        recs = list(measurement_records(u))
        assert len(recs) == 1 and recs[0].time.tzinfo is not None

    def test_epoch_millis_time(self):
        u = _uplink(rxInfo=[{"gatewayId": "gw-1", "rssi": -90, "gwTime": 1762509600000}])
        recs = list(measurement_records(u))
        assert len(recs) == 1 and recs[0].time.year >= 2025
