"""
services/scenarios.py — Pure logic so sánh 2 prediction grid (A/B scenario).

Input: 2 grid (lats, lngs, rssi) cùng độ phân giải.
Output: thống kê coverage diff + per-cell delta.

Tách khỏi DB (Dependency Inversion) — router truyền 2 list dict đã fetch.
"""

from __future__ import annotations

from typing import Iterable

# Đồng bộ với rssiThresholds.js (LoRa Alliance CVT)
RSSI_STRONG = -90
RSSI_MEDIUM = -105
RSSI_WEAK   = -120


def _classify(rssi: float) -> str:
    if rssi >= RSSI_STRONG: return "strong"
    if rssi >= RSSI_MEDIUM: return "medium"
    if rssi >= RSSI_WEAK:   return "weak"
    return "veryWeak"


def _coverage_dist(rssis: Iterable[float]) -> dict:
    """RSSI list → distribution {strong, medium, weak, veryWeak, total, percents}."""
    bins = {"strong": 0, "medium": 0, "weak": 0, "veryWeak": 0}
    total = 0
    for r in rssis:
        bins[_classify(r)] += 1
        total += 1

    if total == 0:
        return {**bins, "total": 0,
                "strongPct": 0, "mediumPct": 0, "weakPct": 0, "veryWeakPct": 0}

    return {
        **bins,
        "total":       total,
        "strongPct":   round(bins["strong"]   / total * 100, 2),
        "mediumPct":   round(bins["medium"]   / total * 100, 2),
        "weakPct":     round(bins["weak"]     / total * 100, 2),
        "veryWeakPct": round(bins["veryWeak"] / total * 100, 2),
    }


def compare_grids(grid_a: list[dict], grid_b: list[dict]) -> dict:
    """
    grid_*: list of {"lat", "lng", "rssi"}.
    Khớp 2 grid theo (lat, lng) → tính per-cell delta = B - A.

    Yêu cầu 2 grid đã được generate cùng campaign cùng resolution.
    """
    rssis_a = [r["rssi"] for r in grid_a]
    rssis_b = [r["rssi"] for r in grid_b]
    dist_a  = _coverage_dist(rssis_a)
    dist_b  = _coverage_dist(rssis_b)

    # Khớp theo (lat, lng) round 5 decimal (~1m) — tránh float noise
    def key(r): return (round(r["lat"], 5), round(r["lng"], 5))

    map_a = {key(r): r["rssi"] for r in grid_a}
    map_b = {key(r): r["rssi"] for r in grid_b}
    common = map_a.keys() & map_b.keys()

    deltas: list[float] = []
    delta_features = []
    for k in common:
        d = map_b[k] - map_a[k]
        deltas.append(d)
        delta_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [k[1], k[0]]},
            "properties": {
                "rssiA":  map_a[k],
                "rssiB":  map_b[k],
                "deltaDb": round(d, 2),
            },
        })

    if deltas:
        avg_delta = sum(deltas) / len(deltas)
        max_gain  = max(deltas)
        max_loss  = min(deltas)
    else:
        avg_delta = max_gain = max_loss = 0.0

    return {
        "summary": {
            "matchedCells":     len(common),
            "onlyInA":          len(map_a) - len(common),
            "onlyInB":          len(map_b) - len(common),
            "avgDeltaDb":       round(avg_delta, 2),
            "maxGainDb":        round(max_gain, 2),
            "maxLossDb":        round(max_loss, 2),
            "strongPctChange":  round(dist_b["strongPct"] - dist_a["strongPct"], 2),
            "mediumPctChange":  round(dist_b["mediumPct"] - dist_a["mediumPct"], 2),
        },
        "distributionA":  dist_a,
        "distributionB":  dist_b,
        "deltaGeoJson":   {"type": "FeatureCollection", "features": delta_features},
    }