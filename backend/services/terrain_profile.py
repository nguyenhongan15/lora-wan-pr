"""
services/terrain_profile.py — DEM-backed terrain sampler cho ITM point-to-point.

Phase 3: Wire `DEM/*.hgt` (NASADEM SRTM-1) vào Longley-Rice ITM p2p mode.
Output đúng ITM profile format (NTIA convention):

  [N, step_m, e0, e1, ..., eN]    với N = số khoảng = số điểm − 1

`itm_wrapper.point_to_point_loss[_py]` đọc trực tiếp array này.

Single source: DEMReader singleton ở `ml/dem.py` (đã lazy-load tiles 1 lần).
Linear interp lat/lng dọc great-circle (sai số <0.1% trong 50km — đủ cho LoRa).
"""

from __future__ import annotations

import numpy as np

from ml.dem import get_dem


def sample_profile(
    tx_lat: float, tx_lng: float,
    rx_lat: float, rx_lng: float,
    *,
    n_samples: int = 64,
) -> np.ndarray:
    """
    Lấy elevation profile từ TX → RX và đóng gói theo ITM format.

    n_samples : số điểm (≥2). NTIA khuyến nghị 50-200 điểm cho ITM p2p.
    Trả ndarray dtype float64 sẵn sàng cho `point_to_point_loss[_py]`.
    """
    if n_samples < 2:
        n_samples = 2

    lats = np.linspace(tx_lat, rx_lat, n_samples)
    lngs = np.linspace(tx_lng, rx_lng, n_samples)

    dem = get_dem()
    elevs = dem.get_elevations_batch(lats.tolist(), lngs.tolist()).astype(np.float64)

    dist_m = _haversine_m(tx_lat, tx_lng, rx_lat, rx_lng)
    n_intervals = n_samples - 1
    step_m = dist_m / n_intervals if n_intervals > 0 else 0.0

    return np.concatenate([[float(n_intervals), float(step_m)], elevs])


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lng2 - lng1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return float(2 * R * np.arctan2(np.sqrt(a), np.sqrt(1 - a)))
