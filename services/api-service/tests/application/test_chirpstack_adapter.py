"""Tests cho ChirpStack adapter — fixtures lấy từ r-dt thật.

Theo unit-test-guide.md §1 — test the interface (input/output mapping),
không test internal helpers.
"""

from __future__ import annotations

from typing import Any

from lora_coverage_api.application.chirpstack_adapter import (
    chirpstack_batch_to_survey_records,
    chirpstack_uplink_to_survey_records,
)


def _uplink(**overrides: Any) -> dict[str, Any]:
    """Uplink hợp lệ tối thiểu (theo r-dt response_..._819822 record 0)."""
    base: dict[str, Any] = {
        "deviceInfo": {"devEui": "a70174b2883514a3", "deviceName": "node01"},
        "txInfo": {
            "frequency": 921400000,
            "modulation": {
                "lora": {
                    "bandwidth": 125000,
                    "codeRate": "CR_4_5",
                    "spreadingFactor": 10,
                }
            },
        },
        "object": {
            "gnss_latitude": 16.0741,
            "gnss_longitude": 108.1525,
        },
        "rxInfo": [
            {
                "gatewayId": "7276ff002e06029f",
                "rssi": -56,
                "snr": 8,
                "gwTime": "2025-12-18T07:04:28.923090+00:00",
            }
        ],
        "time": "2025-12-18T07:04:28.923090+00:00",
    }
    base.update(overrides)
    return base


def test_happy_path_one_rx() -> None:
    r = chirpstack_uplink_to_survey_records(_uplink())
    assert len(r.records) == 1
    assert r.rejected == []
    rec = r.records[0]
    assert rec.spreading_factor == 10
    assert abs(rec.frequency_mhz - 921.4) < 1e-6
    assert rec.rssi_dbm == -56
    assert rec.snr_db == 8
    assert rec.latitude == 16.0741
    assert rec.longitude == 108.1525
    assert rec.serving_gateway_id is None  # resolve sau ở DB layer
    assert rec.device_id == "a70174b2883514a3"


def test_multiple_rx_produces_multiple_records() -> None:
    """1 uplink với N rxInfo → N record (cùng device pos, khác RSSI/SNR)."""
    r = chirpstack_uplink_to_survey_records(
        _uplink(
            rxInfo=[
                {"gatewayId": "gw1", "rssi": -110, "snr": -3},
                {"gatewayId": "gw2", "rssi": -114, "snr": -14},
            ]
        )
    )
    assert len(r.records) == 2
    assert {rec.rssi_dbm for rec in r.records} == {-110, -114}
    # Cùng device location.
    assert all(rec.latitude == 16.0741 for rec in r.records)


def test_reject_missing_txinfo() -> None:
    up = _uplink()
    del up["txInfo"]
    r = chirpstack_uplink_to_survey_records(up)
    assert r.records == []
    assert r.rejected == ["missing txInfo"]


def test_reject_invalid_sf() -> None:
    up = _uplink(
        txInfo={
            "frequency": 921400000,
            "modulation": {"lora": {"spreadingFactor": 99}},
        }
    )
    r = chirpstack_uplink_to_survey_records(up)
    assert r.records == []
    assert "invalid spreadingFactor" in r.rejected[0]


def test_reject_zero_gps() -> None:
    """object.gnss_latitude=0 ⇒ device chưa fix GPS ⇒ reject."""
    up = _uplink(object={"gnss_latitude": 0, "gnss_longitude": 0})
    r = chirpstack_uplink_to_survey_records(up)
    assert r.records == []
    assert "device GPS" in r.rejected[0]


def test_decode_scaled_int_gps() -> None:
    """Decoder gửi GPS dạng degree*1e7 (Cayenne LPP) → tự normalize."""
    up = _uplink(object={"gnss_latitude": 160729548, "gnss_longitude": 1081499147})
    r = chirpstack_uplink_to_survey_records(up)
    assert len(r.records) == 1
    rec = r.records[0]
    assert abs(rec.latitude - 16.0729548) < 1e-6
    assert abs(rec.longitude - 108.1499147) < 1e-6


def test_skip_bad_rx_keep_good_rx() -> None:
    """1 rxInfo xấu KHÔNG làm hỏng các rxInfo khác."""
    r = chirpstack_uplink_to_survey_records(
        _uplink(
            rxInfo=[
                {"gatewayId": "gw1", "rssi": -110, "snr": -3},
                {"gatewayId": "gw2", "rssi": "bad", "snr": -14},
                {"gatewayId": "gw3", "rssi": -120, "snr": -5},
            ]
        )
    )
    assert len(r.records) == 2
    assert any("rxInfo[1]" in m for m in r.rejected)


def test_clip_out_of_range_rssi() -> None:
    """RSSI ngoài [-150, -30] thì record đó bị reject (không kill batch)."""
    r = chirpstack_uplink_to_survey_records(
        _uplink(
            rxInfo=[
                {"rssi": -200, "snr": 0},  # quá thấp
                {"rssi": -56, "snr": 8},  # ok
                {"rssi": -10, "snr": 0},  # quá cao
            ]
        )
    )
    assert len(r.records) == 1
    assert r.records[0].rssi_dbm == -56
    assert sum("out of range" in m for m in r.rejected) == 2


def test_batch_aggregates() -> None:
    r = chirpstack_batch_to_survey_records([_uplink(), _uplink()])
    assert len(r.records) == 2
