"""
services/signal_navigator.py
────────────────────────────
Mô phỏng agent điều hướng đến vùng RSSI tốt hơn (multi-step path).

Inspired by `LoRa_Rssi_Heatmap_Diffusion/search/agent_heatmap_greedy`,
đã đơn giản hoá:
  - Bỏ softmax/temperature (deterministic, không cần PyTorch)
  - Heatmap on-the-fly bằng IDW từ measurements (không cần ML model train)
  - 4 hướng NSEW, mỗi bước step_m mét

Module có 1 public entry-point — find_path_to_better_signal — nhận tọa độ
GPS, trả về polyline waypoints + metrics. Caller (router) lo dịch sang
verdict tiếng Việt qua _classify() có sẵn ở routers/coverage.py.

Stop conditions (theo thứ tự ưu tiên):
  a) RSSI tốt nhất ở 4 neighbor cải thiện < 3 dB so với hiện tại
  b) RSSI hiện tại ≥ −90 dBm (đã "strong", không cần đi tiếp)
  c) Đạt max_steps
  d) Không có measurement nào trong bán kính IDW của tất cả neighbors
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ─────────────────────────────────────────────────────────────
# Constants — không expose ra interface, callers không cần biết
# ─────────────────────────────────────────────────────────────

NO_IMPROVEMENT_THRESHOLD_DB = 3.0     # dừng khi cải thiện < 3 dB
STRONG_RSSI_DBM             = -90.0   # ngưỡng "strong" (LoRa Alliance CVT)
VISITED_PENALTY_DB          = 10.0    # phạt khi neighbor đã ghé qua
IDW_LOOKUP_RADIUS_M         = 100.0   # IDW chỉ dùng measurement <100m
IDW_POWER                   = 2.0
IDW_EPS_M                   = 1.0
METERS_PER_DEG_LAT          = 111139.0  # khớp helper trong source repo


@dataclass(frozen=True)
class _Measurement:
    lat:      float
    lng:      float
    rssi_dbm: float


# 4 hướng NSEW — tuple (dlat_m, dlng_m) chuẩn hoá
_DIRECTIONS: list[tuple[float, float]] = [
    (+1.0,  0.0),  # N
    (-1.0,  0.0),  # S
    ( 0.0, +1.0),  # E
    ( 0.0, -1.0),  # W
]


# ─────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────

def _meters_offset(
    lat: float, lng: float, dlat_m: float, dlng_m: float,
) -> tuple[float, float]:
    """Translate (dlat_m, dlng_m) mét quanh (lat, lng). Approx flat-earth —
    OK với khoảng cách <500m điển hình của 1 vài bước agent."""
    new_lat = lat + dlat_m / METERS_PER_DEG_LAT
    new_lng = lng + dlng_m / (METERS_PER_DEG_LAT * math.cos(math.radians(lat)))
    return new_lat, new_lng


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Khoảng cách trên cầu (mét). Chính xác đủ cho lưới 50m."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _idw_at(meas: list[_Measurement], lat: float, lng: float) -> float | None:
    """IDW RSSI tại (lat, lng) dựa trên measurements trong IDW_LOOKUP_RADIUS_M.
    Trả None nếu không measurement nào đủ gần — caller dựa vào đó để bỏ
    qua candidate."""
    nearby: list[tuple[_Measurement, float]] = []
    for m in meas:
        d = _haversine_m(lat, lng, m.lat, m.lng)
        if d <= IDW_LOOKUP_RADIUS_M:
            nearby.append((m, d))
    if not nearby:
        return None
    weights  = [1.0 / max(d, IDW_EPS_M) ** IDW_POWER for _, d in nearby]
    wsum     = sum(weights)
    rssi_sum = sum(m.rssi_dbm * w for (m, _), w in zip(nearby, weights))
    return rssi_sum / wsum


def _pos_key(lat: float, lng: float) -> tuple[float, float]:
    """Snap to ~1m grid cho visited check (round 5 chữ số)."""
    return (round(lat, 5), round(lng, 5))


async def _load_measurements(
    db: AsyncSession, lat: float, lng: float, radius_m: float,
) -> list[_Measurement]:
    """Query measurements trong bounding circle. Trả raw list — IDW tính sau."""
    rows = (await db.execute(text("""
        SELECT
            ST_Y(location::geometry) AS lat,
            ST_X(location::geometry) AS lng,
            rssi_dbm
        FROM measurements
        WHERE deleted_at IS NULL
          AND location IS NOT NULL
          AND ST_DWithin(
                location::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                :radius
              )
    """), {"lat": lat, "lng": lng, "radius": radius_m})).mappings().all()

    return [
        _Measurement(
            lat=float(r["lat"]), lng=float(r["lng"]),
            rssi_dbm=float(r["rssi_dbm"]),
        )
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

async def find_path_to_better_signal(
    db:              AsyncSession,
    start_lat:       float,
    start_lng:       float,
    max_steps:       int   = 8,
    step_m:          float = 50.0,
    search_radius_m: float = 500.0,
) -> dict:
    """
    Mô phỏng agent N bước đến vùng RSSI tốt nhất cục bộ.

    Args:
        start_lat, start_lng: vị trí xuất phát (WGS84).
        max_steps:            tối đa số bước đi.
        step_m:               độ dài mỗi bước (mét). Lưới NSEW.
        search_radius_m:      bán kính query measurements quanh start.
                              Module tự nới thêm max_steps*step_m để agent
                              có dữ liệu vùng đích.

    Returns:
        dict (camelCase, ready để serialize JSON):
          path:           [{lat, lng, rssiDbm, stepDistanceM}, ...] — phần tử
                          đầu là start, các phần tử sau là từng bước.
          totalDistanceM: tổng quãng đường đi.
          startRssiDbm:   RSSI tại start (None nếu không có measurement gần).
          finalRssiDbm:   RSSI tại waypoint cuối.
          improved:       finalRssi - startRssi ≥ 3 dB.
          stopReason:     "no_improvement" | "reached_strong" | "max_steps"
                          | "no_data".
          samplesUsed:    số measurements load từ DB.
    """
    load_radius = search_radius_m + max_steps * step_m
    meas        = await _load_measurements(db, start_lat, start_lng, load_radius)
    start_rssi  = _idw_at(meas, start_lat, start_lng)

    if start_rssi is None:
        return {
            "path":           [{"lat": start_lat, "lng": start_lng,
                                "rssiDbm": None, "stepDistanceM": 0.0}],
            "totalDistanceM": 0.0,
            "startRssiDbm":   None,
            "finalRssiDbm":   None,
            "improved":       False,
            "stopReason":     "no_data",
            "samplesUsed":    len(meas),
        }

    cur_lat, cur_lng = start_lat, start_lng
    cur_rssi         = start_rssi
    visited          = {_pos_key(cur_lat, cur_lng)}
    path: list[dict] = [{
        "lat":           cur_lat,
        "lng":           cur_lng,
        "rssiDbm":       round(cur_rssi, 1),
        "stepDistanceM": 0.0,
    }]
    total_dist        = 0.0
    stop_reason       = "max_steps"

    for _ in range(max_steps):
        # Stop condition (b) — đã ở vùng strong, không cần đi nữa
        if cur_rssi >= STRONG_RSSI_DBM:
            stop_reason = "reached_strong"
            break

        # Đánh giá 4 neighbors
        candidates: list[dict] = []
        for dlat_m, dlng_m in _DIRECTIONS:
            cand_lat, cand_lng = _meters_offset(cur_lat, cur_lng,
                                                dlat_m * step_m, dlng_m * step_m)
            cand_rssi = _idw_at(meas, cand_lat, cand_lng)
            if cand_rssi is None:
                continue
            score = cand_rssi
            if _pos_key(cand_lat, cand_lng) in visited:
                score -= VISITED_PENALTY_DB
            candidates.append({
                "lat":   cand_lat,
                "lng":   cand_lng,
                "rssi":  cand_rssi,
                "score": score,
            })

        if not candidates:
            stop_reason = "no_data"
            break

        best = max(candidates, key=lambda c: c["score"])

        # Stop condition (a) — không có cải thiện ý nghĩa
        if best["rssi"] - cur_rssi < NO_IMPROVEMENT_THRESHOLD_DB:
            stop_reason = "no_improvement"
            break

        cur_lat, cur_lng, cur_rssi = best["lat"], best["lng"], best["rssi"]
        visited.add(_pos_key(cur_lat, cur_lng))
        path.append({
            "lat":           cur_lat,
            "lng":           cur_lng,
            "rssiDbm":       round(cur_rssi, 1),
            "stepDistanceM": step_m,
        })
        total_dist += step_m

    return {
        "path":           path,
        "totalDistanceM": round(total_dist, 1),
        "startRssiDbm":   round(start_rssi, 1),
        "finalRssiDbm":   round(cur_rssi, 1),
        "improved":       (cur_rssi - start_rssi) >= NO_IMPROVEMENT_THRESHOLD_DB,
        "stopReason":     stop_reason,
        "samplesUsed":    len(meas),
    }
