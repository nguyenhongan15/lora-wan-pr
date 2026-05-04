"""
services/calibration.py — Pure logic cho calibration:
  - Parse CSV ground-truth (lat, lng, rssi_dbm, [snr_db, sf, gateway_eui, measured_at])
  - Tính RMSE / MAE / bias giữa predicted vs measured

Tách hoàn toàn khỏi DB (Dependency Inversion) — router truyền rows đã đọc.
"""

from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timezone
from typing import Iterator

# Header bắt buộc tối thiểu — các cột khác là optional
REQUIRED_COLS = ("lat", "lng", "rssi_dbm")
ALLOWED_COLS  = (*REQUIRED_COLS, "snr_db", "spreading_factor", "gateway_eui", "measured_at")


# ─────────────────────────────────────────────────────────────
# CSV parsing
# ─────────────────────────────────────────────────────────────

def parse_groundtruth_csv(content: bytes) -> Iterator[dict]:
    """
    Yield dict per row hợp lệ. Bỏ qua row sai định dạng (log số lỗi ở caller).

    Format yêu cầu (header bắt buộc): lat, lng, rssi_dbm
    Optional: snr_db, spreading_factor, gateway_eui, measured_at (ISO8601)

    Raise ValueError nếu thiếu header bắt buộc.
    """
    text = content.decode("utf-8-sig")  # tolerant với BOM khi user export từ Excel
    reader = csv.DictReader(io.StringIO(text))

    headers = {h.strip().lower() for h in (reader.fieldnames or [])}
    missing = [c for c in REQUIRED_COLS if c not in headers]
    if missing:
        raise ValueError(f"CSV thiếu cột bắt buộc: {', '.join(missing)}")

    for raw in reader:
        row = {k.strip().lower(): (v.strip() if isinstance(v, str) else v)
               for k, v in raw.items() if k}
        try:
            yield _normalize_row(row)
        except (ValueError, TypeError):
            # row sai định dạng → bỏ; caller đếm số fail qua try/except
            continue


def _normalize_row(row: dict) -> dict:
    lat  = float(row["lat"])
    lng  = float(row["lng"])
    rssi = float(row["rssi_dbm"])

    # Validate physical bounds (đồng bộ ck_measurements_rssi_range)
    if not (-90 <= lat <= 90):       raise ValueError("lat out of range")
    if not (-180 <= lng <= 180):     raise ValueError("lng out of range")
    if not (-200 <= rssi <= 20):     raise ValueError("rssi out of range")

    snr = row.get("snr_db")
    sf  = row.get("spreading_factor")
    ts  = row.get("measured_at")

    return {
        "lat":              lat,
        "lng":              lng,
        "rssi_dbm":         rssi,
        "snr_db":           float(snr) if snr not in (None, "", "null") else None,
        "spreading_factor": int(sf)    if sf  not in (None, "", "null") else None,
        "gateway_eui":      (row.get("gateway_eui") or "").lower() or None,
        "measured_at":      _parse_ts(ts),
    }


def _parse_ts(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    # Hỗ trợ "Z" và offset
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ─────────────────────────────────────────────────────────────
# Metrics — pairs of (predicted, measured)
# ─────────────────────────────────────────────────────────────

def compute_metrics(pairs: list[tuple[float, float]]) -> dict:
    """
    pairs: list[(predicted_dbm, measured_dbm)]
    Return: { rmseDb, maeDb, biasDb, n }  — None nếu không đủ data.
    """
    if not pairs:
        return {"n": 0, "rmseDb": None, "maeDb": None, "biasDb": None}

    n        = len(pairs)
    diffs    = [p - m for p, m in pairs]
    abs_diff = [abs(d) for d in diffs]
    sq_diff  = [d * d for d in diffs]

    return {
        "n":      n,
        "rmseDb": round(math.sqrt(sum(sq_diff) / n), 3),
        "maeDb":  round(sum(abs_diff) / n, 3),
        "biasDb": round(sum(diffs) / n,    3),   # >0 = model dự đoán cao hơn thực tế
    }