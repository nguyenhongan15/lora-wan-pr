"""
tests/unit/test_calibration.py — Unit test cho services.calibration.
"""

from __future__ import annotations

import pytest

from services.calibration import compute_metrics, parse_groundtruth_csv


def test_parse_groundtruth_csv_valid_header_yields_normalized_rows():
    # Arrange
    csv_bytes = b"lat,lng,rssi_dbm\n16.054,108.202,-95.5\n16.060,108.210,-100.0\n"

    # Act
    rows = list(parse_groundtruth_csv(csv_bytes))

    # Assert — đúng số dòng + giá trị numeric
    assert len(rows) == 2
    assert rows[0]["lat"] == 16.054
    assert rows[0]["rssi_dbm"] == -95.5


def test_parse_groundtruth_csv_missing_required_column_raises_value_error():
    # Arrange — thiếu cột rssi_dbm
    csv_bytes = b"lat,lng\n16.054,108.202\n"

    # Act + Assert
    with pytest.raises(ValueError, match="rssi_dbm"):
        list(parse_groundtruth_csv(csv_bytes))


def test_compute_metrics_empty_pairs_returns_n_zero_with_none_metrics():
    # Arrange
    # Act
    metrics = compute_metrics([])

    # Assert
    assert metrics["n"] == 0
    assert metrics["rmseDb"] is None


def test_compute_metrics_known_pairs_returns_correct_rmse_mae_bias():
    # Arrange — predicted, measured: chênh đều +5 dB (model dự đoán cao hơn 5 dB)
    pairs = [(-90, -95), (-100, -105), (-110, -115)]

    # Act
    metrics = compute_metrics(pairs)

    # Assert
    assert metrics["n"] == 3
    assert metrics["biasDb"] == 5.0       # dự đoán cao hơn measured trung bình 5 dB
    assert metrics["maeDb"]  == 5.0
    assert metrics["rmseDb"] == 5.0       # cùng dấu, cùng magnitude