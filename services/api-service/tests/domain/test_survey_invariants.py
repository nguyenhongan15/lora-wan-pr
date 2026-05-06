"""Domain invariants cho SurveyRecord.

Mọi range check là hard invariant — pytest.raises là đúng.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lora_coverage_api.domain.survey import (
    RSSI_MAX_DBM,
    RSSI_MIN_DBM,
    SNR_MAX_DB,
    SNR_MIN_DB,
    SurveyRecord,
)

from ..factories import make_survey_record

_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_survey_record_accepts_defaults_from_factory():
    rec = make_survey_record()

    assert rec.spreading_factor == 7


@pytest.mark.parametrize("bad_lat", [-90.1, 90.1])
def test_survey_record_rejects_latitude_when_outside_geographic_range(
    bad_lat: float,
):
    with pytest.raises(ValueError, match="latitude"):
        make_survey_record(latitude=bad_lat)


@pytest.mark.parametrize("bad_lng", [-180.01, 180.01])
def test_survey_record_rejects_longitude_when_outside_geographic_range(
    bad_lng: float,
):
    with pytest.raises(ValueError, match="longitude"):
        make_survey_record(longitude=bad_lng)


@pytest.mark.parametrize("bad_rssi", [RSSI_MIN_DBM - 0.1, RSSI_MAX_DBM + 0.1, -200.0, 0.0])
def test_survey_record_rejects_rssi_when_outside_lora_dynamic_range(
    bad_rssi: float,
):
    with pytest.raises(ValueError, match="rssi_dbm"):
        make_survey_record(rssi_dbm=bad_rssi)


def test_survey_record_accepts_rssi_at_boundaries():
    rec_min = make_survey_record(rssi_dbm=RSSI_MIN_DBM)
    rec_max = make_survey_record(rssi_dbm=RSSI_MAX_DBM)

    assert rec_min.rssi_dbm == RSSI_MIN_DBM
    assert rec_max.rssi_dbm == RSSI_MAX_DBM


@pytest.mark.parametrize("bad_snr", [SNR_MIN_DB - 0.1, SNR_MAX_DB + 0.1, -100.0, 100.0])
def test_survey_record_rejects_snr_when_outside_physical_range(bad_snr: float):
    with pytest.raises(ValueError, match="snr_db"):
        make_survey_record(snr_db=bad_snr)


@pytest.mark.parametrize("bad_sf", [0, 6, 13, 20])
def test_survey_record_rejects_spreading_factor_when_not_in_lora_range(
    bad_sf: int,
):
    with pytest.raises(ValueError, match="SF"):
        make_survey_record(spreading_factor=bad_sf)


def test_survey_record_preserves_timezone_aware_timestamp():
    rec = SurveyRecord(
        timestamp=_TS,
        latitude=16.05,
        longitude=108.2,
        rssi_dbm=-95.0,
        snr_db=7.5,
        spreading_factor=7,
    )

    assert rec.timestamp.tzinfo is not None
    assert rec.timestamp == _TS
