"""
tests/unit/test_path_loss.py — Unit test cho services.path_loss.

Tuân thủ:
  - A-A-A: Arrange → Act → Assert
  - F.I.R.S.T: pure function, không I/O, chạy <1ms
  - Naming: test_<method>_<state>_<expected>
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from services.path_loss import (
    PATH_LOSS_EXPONENT,
    PL_AT_1M_DB,
    predict_combined_rssi,
    predict_rssi_at,
)


def test_predict_rssi_at_urban_environment_returns_lower_rssi_than_rural():
    # Arrange — cùng tx, cùng khoảng cách, chỉ đổi env
    tx_lat, tx_lng = 16.054, 108.202
    rx_lats = np.array([16.064])    # ~1.1km bắc
    rx_lngs = np.array([108.202])

    # Act
    rssi_urban = predict_rssi_at(tx_lat, tx_lng, rx_lats, rx_lngs, environment="urban")
    rssi_rural = predict_rssi_at(tx_lat, tx_lng, rx_lats, rx_lngs, environment="rural")

    # Assert — urban (n=3.5) suy hao nhiều hơn rural (n=2.5)
    assert rssi_urban[0] < rssi_rural[0]


def test_predict_rssi_at_zero_distance_returns_finite_value_not_log_zero_error():
    # Arrange — rx trùng tx (distance = 0)
    tx_lat, tx_lng = 16.054, 108.202
    rx_lats = np.array([16.054])
    rx_lngs = np.array([108.202])

    # Act
    rssi = predict_rssi_at(tx_lat, tx_lng, rx_lats, rx_lngs)

    # Assert — không inf/nan, vì service clamp distance >= 1m
    assert math.isfinite(rssi[0])


def test_predict_rssi_at_known_distance_matches_log_distance_formula():
    # Arrange — kiểm chứng công thức tại d=100m, urban
    # PL = 40 + 10*3.5*log10(100) = 40 + 70 = 110
    # RSSI = 14 + 8 - 110 = -88
    tx_lat, tx_lng = 0.0, 0.0
    # Tạo rx cách tx ~100m về phía bắc (1° lat ≈ 111km → 100m ≈ 0.0009°)
    rx_lats = np.array([0.000899])
    rx_lngs = np.array([0.0])

    # Act
    rssi = predict_rssi_at(tx_lat, tx_lng, rx_lats, rx_lngs, environment="urban")

    # Assert — sai số ±0.5 dB do haversine xấp xỉ
    assert abs(rssi[0] - (-88.0)) < 1.0


def test_predict_combined_rssi_multiple_transmitters_returns_max_per_cell():
    # Arrange — 2 tx, 1 điểm rx gần tx2 hơn
    transmitters = [
        {"lat": 0.0,    "lng": 0.0},      # xa
        {"lat": 0.001,  "lng": 0.0},      # gần
    ]
    rx_lats = np.array([0.0011])
    rx_lngs = np.array([0.0])

    # Act
    combined = predict_combined_rssi(transmitters, rx_lats, rx_lngs)
    rssi_close = predict_rssi_at(0.001, 0.0, rx_lats, rx_lngs)

    # Assert — best-server: chọn tx gần
    assert combined[0] == pytest.approx(rssi_close[0], abs=0.01)