"""
tests/unit/test_scenarios.py — Unit test cho services.scenarios (P4 A/B compare).
"""

from __future__ import annotations

from services.scenarios import compare_grids


def test_compare_grids_empty_returns_zero_matched_cells():
    # Arrange
    # Act
    result = compare_grids([], [])

    # Assert
    assert result["summary"]["matchedCells"] == 0
    assert result["summary"]["avgDeltaDb"] == 0


def test_compare_grids_b_better_than_a_returns_positive_avg_delta():
    # Arrange — cùng vị trí, B có RSSI tốt hơn A 5 dB
    grid_a = [{"lat": 16.054, "lng": 108.202, "rssi": -100}]
    grid_b = [{"lat": 16.054, "lng": 108.202, "rssi":  -95}]

    # Act
    result = compare_grids(grid_a, grid_b)

    # Assert — delta = B - A = +5 dB
    assert result["summary"]["matchedCells"] == 1
    assert result["summary"]["avgDeltaDb"] == 5.0


def test_compare_grids_no_overlap_returns_zero_matched_only_in_each():
    # Arrange — 2 grid khác vị trí hoàn toàn
    grid_a = [{"lat": 16.054, "lng": 108.202, "rssi": -100}]
    grid_b = [{"lat": 21.028, "lng": 105.804, "rssi":  -90}]

    # Act
    result = compare_grids(grid_a, grid_b)

    # Assert
    assert result["summary"]["matchedCells"] == 0
    assert result["summary"]["onlyInA"] == 1
    assert result["summary"]["onlyInB"] == 1