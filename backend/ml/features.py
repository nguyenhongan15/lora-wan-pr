"""
ml/features.py — Feature engineering cho bài toán hồi quy RSSI LoRa.

Nhận dữ liệu từ DB (measurement + gateway join) và DEM,
trả về DataFrame sẵn sàng đưa vào model.

Feature vector (20 features) theo sơ đồ thiết kế:
  Khoảng cách : log_distance, distance_3d, fresnel_ratio
  DEM         : h_diff, los_flag, terrain_roughness
  OSM         : building_density, land_use_enc, obstacle_count_los
  LoRa params : spreading_factor, antenna_height_tx, freq_mhz
  Hướng & góc : azimuth_sin, azimuth_cos, elevation_sin, elevation_cos
  Đường truyền: max_obstacle_height, terrain_crossings, excess_path_height
  ITM physics : itm_path_loss_db  (ITM P2P khi DEM+DLL có, Hata khi không)
"""

from __future__ import annotations

import math
import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from ml.dem import DEMReader

logger = logging.getLogger(__name__)

# ── Hằng số vật lý ────────────────────────────────────────────────────────────
EARTH_RADIUS_M = 6_371_000.0
DEFAULT_FREQ_MHZ = 923.0   # AS923 (Việt Nam) — khớp services/path_loss.py

# Tên feature sau khi engineer — thứ tự này PHẢI khớp khi train và inference
FEATURE_NAMES: list[str] = [
    # Khoảng cách
    "log_distance",
    "distance_3d",
    "fresnel_ratio",
    # DEM
    "h_diff",
    "los_flag",
    "terrain_roughness",
    # OSM / môi trường
    "building_density",
    "land_use_enc",
    "obstacle_count_los",
    # Tham số LoRa
    "spreading_factor",
    "antenna_height_tx",
    "freq_mhz",
    # Hướng & góc
    "azimuth_sin",
    "azimuth_cos",
    "elevation_sin",
    "elevation_cos",
    # Đường truyền
    "max_obstacle_height",
    "terrain_crossings",
    "excess_path_height",
    # ITM physics — terrain-aware path loss estimate
    "itm_path_loss_db",
]

LAND_USE_MAP = {"urban": 2, "residential": 2, "commercial": 2,
                "rural": 1, "suburban": 1,
                "forest": 0, "water": 0, "unknown": 1}


# ── Geodesic helpers ───────────────────────────────────────────────────────────

def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Khoảng cách mặt đất (m) giữa 2 điểm."""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lng2 - lng1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _azimuth_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Góc phương vị từ điểm 1 → điểm 2 (0°=Bắc, theo chiều kim đồng hồ)."""
    dλ = math.radians(lng2 - lng1)
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    x = math.sin(dλ) * math.cos(φ2)
    y = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(dλ)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _elevation_angle_deg(
    dist_2d_m: float, h_tx_m: float, h_rx_m: float
) -> float:
    """Góc ngẩng từ thiết bị (RX) nhìn lên gateway (TX)."""
    if dist_2d_m < 1:
        return 90.0
    return math.degrees(math.atan2(h_tx_m - h_rx_m, dist_2d_m))


# ── DEM profile helpers ────────────────────────────────────────────────────────

def _sample_profile(
    dem: "DEMReader",
    lat_tx: float, lng_tx: float,
    lat_rx: float, lng_rx: float,
    n_samples: int = 20,
) -> np.ndarray:
    """
    Lấy profile độ cao dọc đường truyền TX→RX.
    Trả về mảng độ cao (m), độ dài n_samples.
    """
    lats = np.linspace(lat_tx, lat_rx, n_samples)
    lngs = np.linspace(lng_tx, lng_rx, n_samples)
    return np.array([dem.get_elevation(la, lo) for la, lo in zip(lats, lngs)],
                    dtype=float)


def _compute_path_features(
    profile: np.ndarray,
    h_tx: float, h_rx: float,
    dist_2d: float,
) -> dict[str, float]:
    """
    Tính các feature từ profile độ cao:
      - los_flag          : 1=thoáng, 0=bị chắn (so sánh với đường thẳng TX-RX)
      - max_obstacle_height: vật cản cao nhất vượt quá đường thẳng (m)
      - terrain_crossings : số lần địa hình cắt đường thẳng TX-RX
      - excess_path_height: tổng lượng vượt quá (m)
      - terrain_roughness : độ lệch chuẩn của profile
    """
    n = len(profile)
    if n < 2:
        return dict(los_flag=1.0, max_obstacle_height=0.0,
                    terrain_crossings=0.0, excess_path_height=0.0,
                    terrain_roughness=0.0)

    # Đường thẳng TX→RX theo chiều thẳng đứng
    line = np.linspace(h_tx, h_rx, n)
    diff = profile - line               # dương → địa hình cao hơn đường thẳng

    crossings = int(np.sum(np.diff(np.sign(diff)) != 0))
    max_obs   = float(max(diff.max(), 0.0))
    excess    = float(np.clip(diff, 0, None).sum())
    roughness = float(profile.std())
    los       = 1.0 if max_obs <= 0 else 0.0

    return dict(
        los_flag=los,
        max_obstacle_height=max_obs,
        terrain_crossings=float(crossings),
        excess_path_height=excess,
        terrain_roughness=roughness,
    )


# ── ITM physics feature ───────────────────────────────────────────────────────

def _compute_itm_path_loss(
    dist_2d: float,
    h_tx: float,
    h_rx: float,
    freq: float,
    dem: "DEMReader | None",
    lat_tx: float, lng_tx: float,
    lat_rx: float, lng_rx: float,
) -> float:
    """
    Feature itm_path_loss_db — ước tính path loss dựa trên vật lý ITM.

    Ưu tiên:
      1. ITM point-to-point với terrain profile thực (DEM + DLL cả hai có)
      2. ITM point-to-point Python fallback (DEM có, DLL không)
      3. ITM area-mode Python với deltaH từ terrain roughness (DEM không có)

    Feature này cho ML model một "prior" vật lý mạnh, giảm đáng kể
    sai số so với chỉ dùng log_distance.
    """
    try:
        from ml import itm_wrapper  # lazy import, tránh load DLL ở import time

        if dem is not None and dem.tiles:
            # Có DEM → dùng terrain profile thực (P2P mode, chính xác hơn)
            profile = _sample_profile(dem, lat_tx, lng_tx, lat_rx, lng_rx, n_samples=30)
            elev_arr = itm_wrapper.make_itm_elev(profile, dist_2d)

            if itm_wrapper.DLL_AVAILABLE:
                dbloss, errnum = itm_wrapper.point_to_point_loss(
                    elev_arr, h_tx, h_rx, freq
                )
                if errnum < 4:
                    return float(dbloss)

            # DLL không có hoặc lỗi → Python P2P fallback
            return itm_wrapper.point_to_point_loss_py(elev_arr, h_tx, h_rx, freq)

        else:
            # Không có DEM → area mode với deltaH mặc định (rural flat)
            return itm_wrapper.area_mode_loss_py(
                dist_km=max(dist_2d, 1.0) / 1000.0,
                delta_h=10.0,   # rural flat làm baseline khi không biết địa hình
                tht_m=max(h_tx, 1.0),
                rht_m=max(h_rx, 0.5),
                frq_mhz=freq,
            )

    except Exception as exc:
        logger.debug("itm_feature_error: %s", exc)
        # Last resort: Hata urban inline (không import services để tránh circular)
        d_km = max(dist_2d, 1.0) / 1000.0
        log_f = math.log10(freq)
        log_hb = math.log10(max(h_tx, 1.0))
        a_hm = (1.1 * log_f - 0.7) * min(max(h_rx, 0.5), 10.0) - (1.56 * log_f - 0.8)
        return 69.55 + 26.16 * log_f - 13.82 * log_hb - a_hm + (44.9 - 6.55 * log_hb) * math.log10(d_km)


# ── Fresnel zone ───────────────────────────────────────────────────────────────

def _fresnel_ratio(dist_2d: float, freq_mhz: float, max_obs_h: float) -> float:
    """
    Tỉ lệ Fresnel: bán kính zone 1 tại midpoint / chiều cao vật cản.
    Giá trị > 1 → LOS đủ thoáng.
    """
    wavelength = 3e8 / (freq_mhz * 1e6 + 1e-9)
    r1 = math.sqrt(wavelength * dist_2d / 4)   # bán kính Fresnel zone 1 tại mid
    return r1 / (max_obs_h + 1e-3)


# ── Main engineer function ─────────────────────────────────────────────────────

def engineer_row(
    row: dict,
    dem: "DEMReader | None" = None,
) -> dict[str, float]:
    """
    Tính feature vector cho MỘT điểm đo.

    row cần có:
        lat_rx, lng_rx          — tọa độ thiết bị
        lat_tx, lng_tx          — tọa độ gateway
        h_rx (device altitude_m, mặc định 1.5)
        h_tx (gateway antenna_height_m, mặc định 10)
        spreading_factor        (mặc định 9)
        freq_mhz                (mặc định 868)
        building_density        (mặc định 0.3)
        land_use                (mặc định "rural")
        obstacle_count_los      (mặc định 0)
    """
    lat_rx  = float(row["lat_rx"])
    lng_rx  = float(row["lng_rx"])
    lat_tx  = float(row["lat_tx"])
    lng_tx  = float(row["lng_tx"])
    h_rx    = float(row.get("h_rx") or 1.5)
    h_tx    = float(row.get("h_tx") or 10.0)
    sf      = float(row.get("spreading_factor") or 9)
    freq    = float(row.get("freq_mhz") or DEFAULT_FREQ_MHZ)
    bd      = float(row.get("building_density") or 0.3)
    lu_raw  = str(row.get("land_use") or "rural").lower()
    obs_cnt = float(row.get("obstacle_count_los") or 0)

    # ── Khoảng cách ─────────────────────────────────────────
    dist_2d  = _haversine_m(lat_rx, lng_rx, lat_tx, lng_tx)
    h_diff   = h_tx - h_rx
    dist_3d  = math.sqrt(dist_2d ** 2 + h_diff ** 2)
    log_dist = math.log1p(dist_2d)

    # ── Hướng & góc ─────────────────────────────────────────
    az   = _azimuth_deg(lat_rx, lng_rx, lat_tx, lng_tx)
    el   = _elevation_angle_deg(dist_2d, h_tx, h_rx)
    az_r = math.radians(az)
    el_r = math.radians(el)

    # ── DEM features ─────────────────────────────────────────
    path_feat = dict(los_flag=1.0, max_obstacle_height=0.0,
                     terrain_crossings=0.0, excess_path_height=0.0,
                     terrain_roughness=0.0)
    if dem is not None and dem.tiles:
        try:
            profile = _sample_profile(dem, lat_tx, lng_tx, lat_rx, lng_rx)
            path_feat = _compute_path_features(profile, h_tx, h_rx, dist_2d)
        except Exception as e:
            logger.debug("DEM profile error: %s", e)

    # ── Fresnel ──────────────────────────────────────────────
    fresnel = _fresnel_ratio(dist_2d, freq, path_feat["max_obstacle_height"])

    # ── Land use encode ──────────────────────────────────────
    lu_enc = float(LAND_USE_MAP.get(lu_raw, 1))

    # ── ITM physics feature ──────────────────────────────────
    itm_pl = _compute_itm_path_loss(
        dist_2d=dist_2d,
        h_tx=h_tx, h_rx=h_rx,
        freq=freq,
        dem=dem,
        lat_tx=lat_tx, lng_tx=lng_tx,
        lat_rx=lat_rx, lng_rx=lng_rx,
    )

    return {
        "log_distance"       : log_dist,
        "distance_3d"        : dist_3d,
        "fresnel_ratio"      : fresnel,
        "h_diff"             : h_diff,
        "los_flag"           : path_feat["los_flag"],
        "terrain_roughness"  : path_feat["terrain_roughness"],
        "building_density"   : bd,
        "land_use_enc"       : lu_enc,
        "obstacle_count_los" : obs_cnt,
        "spreading_factor"   : sf,
        "antenna_height_tx"  : h_tx,
        "freq_mhz"           : freq,
        "azimuth_sin"        : math.sin(az_r),
        "azimuth_cos"        : math.cos(az_r),
        "elevation_sin"      : math.sin(el_r),
        "elevation_cos"      : math.cos(el_r),
        "max_obstacle_height": path_feat["max_obstacle_height"],
        "terrain_crossings"  : path_feat["terrain_crossings"],
        "excess_path_height" : path_feat["excess_path_height"],
        "itm_path_loss_db"   : itm_pl,
    }


def engineer_dataframe(rows: list[dict], dem: "DEMReader | None" = None) -> pd.DataFrame:
    """
    Tính feature vector cho danh sách điểm đo.
    Trả về DataFrame với cột theo thứ tự FEATURE_NAMES.
    """
    records = []
    for r in rows:
        try:
            feat = engineer_row(r, dem)
            records.append(feat)
        except Exception as e:
            logger.warning("engineer_row error (skip): %s", e)

    if not records:
        return pd.DataFrame(columns=FEATURE_NAMES)

    df = pd.DataFrame(records)
    # Đảm bảo đúng thứ tự và không thiếu cột
    for col in FEATURE_NAMES:
        if col not in df.columns:
            df[col] = 0.0
    return df[FEATURE_NAMES].fillna(0.0)