"""
tests/unit/test_sandbox.py — Unit test cho services.sandbox (P6 custom env).
"""

from __future__ import annotations

from services.sandbox import predict_point, predict_radial_profile


def test_predict_point_short_distance_strong_signal_returns_decodeable_true():
    # Arrange — tx và rx cách nhau ~700m, urban, SF9
    # Act
    result = predict_point(
        tx_lat=16.054, tx_lng=108.202,
        rx_lat=16.060, rx_lng=108.202,
        environment="urban", spreading_factor=9,
    )

    # Assert — RSSI cao, link margin > 0
    assert result["decodeable"] is True
    assert result["linkMarginDb"] > 0


def test_predict_point_far_distance_weak_signal_returns_decodeable_false():
    # Arrange — tx và rx cách nhau ~50km, urban, SF7 (kém nhạy nhất)
    # Act
    result = predict_point(
        tx_lat=16.054, tx_lng=108.202,
        rx_lat=16.500, rx_lng=108.202,
        environment="urban", spreading_factor=7,
    )

    # Assert — vượt sensitivity → không decode được
    assert result["decodeable"] is False
    assert result["level"] == "none"


def test_predict_point_path_loss_exponent_override_takes_priority_over_environment():
    # Arrange — environment="urban" (n=3.5) nhưng override n=2.0 → nên dùng 2.0
    # Act
    result = predict_point(
        tx_lat=0.0, tx_lng=0.0,
        rx_lat=0.001, rx_lng=0.0,
        environment="urban",
        path_loss_exponent_override=2.0,
    )

    # Assert
    assert result["pathLossExponent"] == 2.0


def test_predict_radial_profile_returns_n_samples_with_decreasing_rssi():
    # Arrange
    # Act
    points = predict_radial_profile(
        tx_lat=0.0, tx_lng=0.0,
        max_distance_m=5000, n_samples=50,
        environment="urban",
    )

    # Assert — đúng số mẫu + RSSI giảm dần theo distance (monotonic)
    assert len(points) == 50
    rssis = [p["rssiDbm"] for p in points]
    assert all(rssis[i] >= rssis[i + 1] for i in range(len(rssis) - 1))