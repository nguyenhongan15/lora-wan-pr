"""
tests/unit/test_exporters.py — Unit test cho services.exporters.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.exporters import measurements_to_geojson, measurements_to_kml


SAMPLE_ROW = {
    "lat":              16.054,
    "lng":              108.202,
    "rssi_dbm":         -95.0,
    "snr_db":           7.5,
    "spreading_factor": 9,
    "measured_at":      datetime(2026, 1, 1, tzinfo=timezone.utc),
}


def test_measurements_to_geojson_valid_row_returns_rfc7946_feature_collection():
    # Arrange
    rows = [SAMPLE_ROW]

    # Act
    result = measurements_to_geojson(rows)

    # Assert — RFC 7946: type=FeatureCollection, geometry=Point, [lng, lat]
    assert result["type"] == "FeatureCollection"
    assert result["features"][0]["geometry"]["type"] == "Point"
    assert result["features"][0]["geometry"]["coordinates"] == [108.202, 16.054]


def test_measurements_to_kml_strong_rssi_uses_strong_style_id():
    # Arrange — RSSI = -85 dBm → ngưỡng "strong" (≥ -90)
    rows = [{**SAMPLE_ROW, "rssi_dbm": -85.0}]

    # Act
    kml = measurements_to_kml(rows, "Test Campaign")

    # Assert — XML KML 2.2, có placemark với styleUrl=#strong
    assert "<kml" in kml
    assert "xmlns=\"http://www.opengis.net/kml/2.2\"" in kml
    assert "#strong" in kml