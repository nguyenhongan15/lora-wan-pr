"""
routers/coverage.py
───────────────────
End-user coverage check (Persona 5).

Mục tiêu: trả về câu trả lời "Có/Không có sóng" tại 1 toạ độ GPS,
KHÔNG trưng RSSI/SNR/SF kỹ thuật cho user cuối.

  GET /coverage/check        → level + verdict tiếng Việt + gateway gần nhất
  GET /coverage/suggest-move → bearing + khoảng cách đến vị trí có sóng tốt hơn

Tuân thủ:
  - API Contract: camelCase JSON, response wrapper, /api/v1 prefix
  - LoRa Alliance CVT thresholds: Strong ≥ −90, Medium ≥ −105, Weak ≥ −120
  - rulefordesigndatabase.pdf: bảng plural, deleted_at IS NULL filter
  - SOLID SRP: router gọn, logic tính toán tách thành helper thuần
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import ValidationError
from core.responses import ok
from database import get_db
from services.rf_predictor import RSSI_MEDIUM, classify as _classify
from services.signal_navigator import find_path_to_better_signal

router = APIRouter(prefix="/coverage", tags=["coverage"])

# RSSI thresholds + classify giờ tới từ rf_predictor (single source of truth,
# đồng bộ FE rssiThresholds.js + sandbox + simulator).


# ─────────────────────────────────────────────────────────────
# Pure helpers (testable, không phụ thuộc DB)
# ─────────────────────────────────────────────────────────────

def _bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Bearing (0=Bắc, 90=Đông) từ (lat1,lng1) đến (lat2,lng2)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _direction_vi(deg: float) -> str:
    """Bearing → hướng tiếng Việt (8 hướng)."""
    dirs = ["Bắc", "Đông Bắc", "Đông", "Đông Nam",
            "Nam", "Tây Nam", "Tây", "Tây Bắc"]
    return dirs[round(deg / 45) % 8]


def _idw(rows: list[dict], power: float = 2.0, eps_m: float = 1.0) -> float:
    """IDW weighted average. Eps tránh chia 0 khi user đứng đúng trên điểm đo."""
    weights = [1.0 / max(r["dist_m"], eps_m) ** power for r in rows]
    wsum    = sum(weights)
    return sum(r["rssi_dbm"] * w for r, w in zip(rows, weights)) / wsum


def _validate_coords(lat: float, lng: float) -> None:
    if not -90 <= lat <= 90:
        raise ValidationError("lat phải trong [-90, 90]", code="INVALID_LATITUDE")
    if not -180 <= lng <= 180:
        raise ValidationError("lng phải trong [-180, 180]", code="INVALID_LONGITUDE")


# ─────────────────────────────────────────────────────────────
# GET /coverage/check
# ─────────────────────────────────────────────────────────────

@router.get("/check")
async def check_coverage(
    lat:      float = Query(..., description="Vĩ độ (WGS84)"),
    lng:      float = Query(..., description="Kinh độ (WGS84)"),
    radius_m: int   = Query(300, ge=50, le=2000, alias="radiusM"),
    db:       AsyncSession = Depends(get_db),
):
    """
    Trả về tình trạng phủ sóng tại 1 toạ độ.

    Logic:
      1. Tìm measurements trong bán kính `radiusM` (default 300m, max 2km)
      2. Nếu có ≥1 mẫu → IDW power=2 → predicted RSSI → classify
      3. Tìm gateway gần nhất bất kể measurements
    """
    _validate_coords(lat, lng)

    rows = (await db.execute(text("""
        SELECT
            rssi_dbm,
            ST_Distance(
                location::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
            ) AS dist_m
        FROM measurements
        WHERE deleted_at IS NULL
          AND location IS NOT NULL
          AND ST_DWithin(
                location::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                :radius
              )
        ORDER BY dist_m ASC
        LIMIT 20
    """), {"lat": lat, "lng": lng, "radius": radius_m})).mappings().all()

    predicted: float | None = _idw([dict(r) for r in rows]) if rows else None
    level, verdict          = _classify(predicted)

    # Gateway gần nhất — KNN qua PostGIS <-> operator (cần GIST index ở schema)
    gw = (await db.execute(text("""
        SELECT
            id::text                         AS id,
            name,
            gateway_eui,
            ST_X(location::geometry)         AS lng,
            ST_Y(location::geometry)         AS lat,
            ST_Distance(
                location::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
            ) AS dist_m
        FROM gateways
        WHERE deleted_at IS NULL AND location IS NOT NULL
        ORDER BY location <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
        LIMIT 1
    """), {"lat": lat, "lng": lng})).mappings().first()

    nearest = None
    if gw:
        bearing = _bearing_deg(lat, lng, gw["lat"], gw["lng"])
        nearest = {
            "id":         gw["id"],
            "name":       gw["name"],
            "gatewayEui": gw["gateway_eui"],
            "distanceM":  round(float(gw["dist_m"]), 1),
            "bearingDeg": round(bearing, 1),
            "direction":  _direction_vi(bearing),
        }

    return ok({
        "lat":              lat,
        "lng":              lng,
        "level":            level,
        "verdict":          verdict,
        "predictedRssiDbm": round(predicted, 1) if predicted is not None else None,
        "samplesUsed":      len(rows),
        "radiusM":          radius_m,
        "nearestGateway":   nearest,
    })


# ─────────────────────────────────────────────────────────────
# GET /coverage/suggest-move
# ─────────────────────────────────────────────────────────────

@router.get("/suggest-move")
async def suggest_move(
    lat:             float = Query(..., description="Vĩ độ hiện tại"),
    lng:             float = Query(..., description="Kinh độ hiện tại"),
    search_radius_m: int   = Query(500, ge=100, le=3000, alias="searchRadiusM"),
    db:              AsyncSession = Depends(get_db),
):
    """
    Gợi ý hướng + khoảng cách đến điểm gần nhất có sóng ≥ Medium (−105 dBm).

    Trả về `found=False` nếu không có điểm nào tốt hơn trong bán kính tìm kiếm,
    để frontend hiển thị thông báo phù hợp thay vì gợi ý sai.
    """
    _validate_coords(lat, lng)

    rows = (await db.execute(text("""
        SELECT
            rssi_dbm,
            ST_X(location::geometry) AS lng,
            ST_Y(location::geometry) AS lat,
            ST_Distance(
                location::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
            ) AS dist_m
        FROM measurements
        WHERE deleted_at IS NULL
          AND location IS NOT NULL
          AND rssi_dbm >= :min_rssi
          AND ST_DWithin(
                location::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                :radius
              )
        ORDER BY rssi_dbm DESC, dist_m ASC
        LIMIT 5
    """), {
        "lat": lat, "lng": lng,
        "radius": search_radius_m, "min_rssi": RSSI_MEDIUM,
    })).mappings().all()

    if not rows:
        return ok({
            "found":   False,
            "message": f"Không tìm thấy vị trí có sóng tốt hơn trong "
                       f"{search_radius_m}m quanh bạn.",
        })

    # Trong top 5 RSSI tốt nhất, chọn điểm GẦN NHẤT để dễ di chuyển
    best     = min(rows, key=lambda r: r["dist_m"])
    bearing  = _bearing_deg(lat, lng, best["lat"], best["lng"])
    dir_vi   = _direction_vi(bearing)
    distance = round(float(best["dist_m"]))
    level, verdict = _classify(float(best["rssi_dbm"]))

    return ok({
        "found":            True,
        "bearingDeg":       round(bearing, 1),
        "distanceM":        distance,
        "direction":        dir_vi,
        "expectedLevel":    level,
        "expectedVerdict":  verdict,
        "predictedRssiDbm": round(float(best["rssi_dbm"]), 1),
        "message":          f"Di chuyển khoảng {distance}m về hướng {dir_vi}",
    })


# ─────────────────────────────────────────────────────────────
# GET /coverage/path-to-coverage
# Khác /suggest-move (1 bearing duy nhất): trả full polyline waypoints
# để frontend vẽ đường đi trên map. Logic mô phỏng agent ở
# services/signal_navigator.
# ─────────────────────────────────────────────────────────────

_STOP_REASON_MESSAGE_VI = {
    "no_improvement": "Đã đến vùng tốt nhất cục bộ — không hướng nào cải thiện rõ rệt.",
    "reached_strong": "Đã đạt vùng sóng mạnh.",
    "max_steps":      "Đã đi hết số bước cho phép.",
    "no_data":        "Không đủ dữ liệu đo trong vùng để tìm đường.",
}


@router.get("/path-to-coverage")
async def path_to_coverage(
    lat:             float = Query(..., description="Vĩ độ hiện tại"),
    lng:             float = Query(..., description="Kinh độ hiện tại"),
    max_steps:       int   = Query(8,    ge=1,  le=20,    alias="maxSteps"),
    step_m:          float = Query(50.0, ge=10, le=200,   alias="stepM"),
    search_radius_m: int   = Query(500,  ge=100, le=2000, alias="searchRadiusM"),
    db:              AsyncSession = Depends(get_db),
):
    """
    Mô phỏng đường đi đến vùng tín hiệu tốt hơn (multi-step path).

    Dùng IDW từ measurements thực tế làm heatmap nguồn (không cần ML model).
    Trả waypoints polyline + level/verdict tiếng Việt cho từng điểm.
    """
    _validate_coords(lat, lng)

    result = await find_path_to_better_signal(
        db, lat, lng,
        max_steps=max_steps, step_m=step_m, search_radius_m=search_radius_m,
    )

    # Enrich từng waypoint với level + verdict tiếng Việt
    for wp in result["path"]:
        level, verdict = _classify(wp["rssiDbm"])
        wp["level"]    = level
        wp["verdict"]  = verdict

    final_level, final_verdict = _classify(result["finalRssiDbm"])
    start_level, _             = _classify(result["startRssiDbm"])

    return ok({
        **result,
        "startLevel":    start_level,
        "finalLevel":    final_level,
        "finalVerdict":  final_verdict,
        "message":       _STOP_REASON_MESSAGE_VI.get(result["stopReason"], ""),
    })