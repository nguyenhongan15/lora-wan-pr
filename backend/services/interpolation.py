"""
services/interpolation.py — IDW, Kriging, RBF, Delaunay interpolation.

Bốn phương pháp spatial interpolation cho RSSI LoRa:

  IDW      — Inverse Distance Weighted. Nhanh, ổn định, DEM-aware.
             Tốt cho: dữ liệu đều, cần kết quả ngay.

  Kriging  — Ordinary Kriging (pykrige). Có uncertainty chuẩn thống kê.
             Tốt cho: phân tích chuyên sâu, cần confidence interval.

  RBF      — Radial Basis Function (scipy RBFInterpolator).
             Smooth hơn IDW, không cần variogram như Kriging.
             Corner-anchoring ngăn extrapolation bùng nổ tại biên.
             Tốt cho: dữ liệu thưa, cần bề mặt mượt.

  Delaunay — Delaunay triangulation + barycentric linear interpolation.
             Chính xác tuyệt đối tại data points. Nhanh nhất.
             Tốt cho: dữ liệu dày, muốn giữ nguyên giá trị đo.

References:
  - Shepard (1968), "A two-dimensional interpolation function for irregularly
    spaced data" — IDW
  - Cressie (1993), "Statistics for Spatial Data" — Kriging
  - Hardy (1971), "Multiquadric equations of topography" — RBF
  - Delaunay (1934), "Sur la sphère vide" — Delaunay triangulation
  - LoRa-survey-heatmap (corner anchoring technique)
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np

from ml.dem import get_dem
from services.grid import bbox_with_padding, make_grid

logger = logging.getLogger(__name__)

InterpMethod = Literal["idw", "kriging", "rbf", "delaunay"]


# ─────────────────────────────────────────────────────────────────────────────
# IDW
# ─────────────────────────────────────────────────────────────────────────────

def _idw(
    lats: np.ndarray, lngs: np.ndarray, rssis: np.ndarray,
    grid_lats: np.ndarray, grid_lngs: np.ndarray,
    power: float, k: int,
    use_elevation: bool = False,
    elev_known: np.ndarray | None = None,
    elev_grid:  np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Inverse Distance Weighted, optionally gated bởi elevation difference."""
    from scipy.spatial import cKDTree

    known = np.column_stack([lats, lngs])
    grid  = np.column_stack([grid_lats, grid_lngs])

    tree = cKDTree(known)
    k = min(k, len(known))
    dists, idxs = tree.query(grid, k=k)
    dists   = np.where(dists == 0, 1e-10, dists)
    weights = 1.0 / (dists ** power)

    if use_elevation and elev_known is not None and elev_grid is not None:
        elev_diff  = np.abs(elev_known[idxs] - elev_grid[:, None])
        elev_sigma = max(float(elev_known.std()), 10.0)
        weights   *= np.exp(-0.5 * (elev_diff / elev_sigma) ** 2)

    w_sum = weights.sum(axis=1, keepdims=True)
    w_sum = np.where(w_sum == 0, 1e-10, w_sum)
    w_norm    = weights / w_sum
    vals      = rssis[idxs]
    predicted = (w_norm * vals).sum(axis=1)
    variance  = (w_norm * (vals - predicted[:, None]) ** 2).sum(axis=1)
    unc       = np.sqrt(np.clip(variance, 0, None))
    return predicted, unc


# ─────────────────────────────────────────────────────────────────────────────
# Kriging
# ─────────────────────────────────────────────────────────────────────────────

def _kriging(
    lats: np.ndarray, lngs: np.ndarray, rssis: np.ndarray,
    grid_lats: np.ndarray, grid_lngs: np.ndarray,
    variogram_model: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Ordinary Kriging via pykrige."""
    from pykrige.ok import OrdinaryKriging

    ok = OrdinaryKriging(
        lngs, lats, rssis,
        variogram_model=variogram_model,
        verbose=False, enable_plotting=False,
    )
    z, ss = ok.execute("grid", np.unique(grid_lngs), np.unique(grid_lats))
    return z.data.flatten(), np.sqrt(np.abs(ss.data.flatten()))


# ─────────────────────────────────────────────────────────────────────────────
# RBF (Radial Basis Function)
# ─────────────────────────────────────────────────────────────────────────────

def _rbf(
    lats: np.ndarray, lngs: np.ndarray, rssis: np.ndarray,
    grid_lats: np.ndarray, grid_lngs: np.ndarray,
    kernel: str = "linear",
    anchoring: bool = True,
    smoothing: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Radial Basis Function interpolation (scipy RBFInterpolator).

    kernel: 'linear' | 'thin_plate_spline' | 'multiquadric' |
            'inverse_multiquadric' | 'gaussian' | 'cubic'

    anchoring: Thêm 4 corner points với RSSI = mean(data) để ngăn
               extrapolation bùng nổ tại biên bbox (kỹ thuật từ
               LoRa-survey-heatmap). Quan trọng khi data points thưa.

    smoothing: 0 = nội suy chính xác tại data points.
               > 0 = làm mượt (ít nhạy cảm với noise). Đơn vị: dB².
    """
    from scipy.interpolate import RBFInterpolator

    lats_w = lats.copy()
    lngs_w = lngs.copy()
    vals_w = rssis.copy()

    if anchoring:
        # Margin = 5% extent của data, tối thiểu ~500m tính bằng độ
        lat_margin = max((lats.max() - lats.min()) * 0.05, 5e-3)
        lng_margin = max((lngs.max() - lngs.min()) * 0.05, 5e-3)
        mean_rssi  = float(rssis.mean())

        # 4 corner + 4 midpoint biên — tổng 8 anchor points
        c_lats = [
            lats.min() - lat_margin, lats.min() - lat_margin,
            lats.max() + lat_margin, lats.max() + lat_margin,
            lats.min() - lat_margin, lats.max() + lat_margin,
            lats.mean(),             lats.mean(),
        ]
        c_lngs = [
            lngs.min() - lng_margin, lngs.max() + lng_margin,
            lngs.min() - lng_margin, lngs.max() + lng_margin,
            lngs.mean(),             lngs.mean(),
            lngs.min() - lng_margin, lngs.max() + lng_margin,
        ]
        lats_w = np.concatenate([lats_w, c_lats])
        lngs_w = np.concatenate([lngs_w, c_lngs])
        vals_w = np.concatenate([vals_w, [mean_rssi] * len(c_lats)])

    known_pts = np.column_stack([lats_w, lngs_w])
    grid_pts  = np.column_stack([grid_lats, grid_lngs])

    rbf = RBFInterpolator(
        known_pts, vals_w,
        kernel=kernel,
        smoothing=smoothing,
        neighbors=min(64, len(known_pts)),   # sparse solver cho tập lớn
    )
    predicted = rbf(grid_pts)

    # Uncertainty: khoảng cách đến điểm đo gần nhất — gần → tin cậy, xa → không chắc
    from scipy.spatial import cKDTree
    tree = cKDTree(np.column_stack([lats, lngs]))
    nn_dist, _ = tree.query(grid_pts, k=1)
    sigma_rssi = max(float(rssis.std()), 1.0)
    nn_max     = float(nn_dist.max()) + 1e-10
    unc        = (nn_dist / nn_max) * sigma_rssi

    return predicted, unc


# ─────────────────────────────────────────────────────────────────────────────
# Delaunay
# ─────────────────────────────────────────────────────────────────────────────

def _delaunay(
    lats: np.ndarray, lngs: np.ndarray, rssis: np.ndarray,
    grid_lats: np.ndarray, grid_lngs: np.ndarray,
    method: Literal["linear", "cubic"] = "linear",
    fill_outside: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Delaunay triangulation + barycentric interpolation (scipy griddata).

    Chính xác tuyệt đối tại data points (error = 0 tại mọi điểm đo).
    Nhanh nhất trong 4 phương pháp.

    method:
      'linear' — linear barycentric, C0 continuous (mặc định).
      'cubic'  — Clough-Tocher C1 continuous, mượt hơn nhưng chậm hơn.

    fill_outside:
      True  — Vùng ngoài convex hull được fill bằng nearest-neighbor
              (không có lỗ trên bản đồ, uncertainty = cao).
      False — Vùng ngoài convex hull = NaN (bị loại khỏi grid).
    """
    from scipy.interpolate import griddata
    from scipy.spatial import cKDTree

    known_pts = np.column_stack([lats, lngs])
    grid_pts  = np.column_stack([grid_lats, grid_lngs])

    # Linear/cubic trong convex hull, NaN ngoài hull
    z = griddata(known_pts, rssis, grid_pts, method=method)

    outside_hull = np.isnan(z)
    sigma_rssi   = max(float(rssis.std()), 1.0)

    if fill_outside and outside_hull.any():
        # Nearest-neighbor để fill vùng ngoài hull
        z_nearest   = griddata(known_pts, rssis, grid_pts, method="nearest")
        z            = np.where(outside_hull, z_nearest, z)

    # Uncertainty:
    #   - Trong hull : tỉ lệ khoảng cách đến điểm đo gần nhất
    #   - Ngoài hull : sigma_rssi * (1 + distance_factor) — kém tin cậy hơn
    tree     = cKDTree(known_pts)
    nn_dist, _ = tree.query(grid_pts, k=1)
    nn_max   = float(nn_dist.max()) + 1e-10
    dist_fac = nn_dist / nn_max

    unc = np.where(
        outside_hull,
        sigma_rssi * (1.0 + dist_fac),   # ngoài hull
        dist_fac * sigma_rssi,            # trong hull
    )

    return z, unc


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def interpolate(
    lats:  list[float],
    lngs:  list[float],
    rssis: list[float],
    *,
    method:          InterpMethod,
    resolution_m:    int,
    # IDW params
    idw_power:       float = 2.0,
    idw_neighbors:   int   = 12,
    # Kriging params
    kriging_model:   str   = "spherical",
    # RBF params
    rbf_function:    str   = "linear",
    rbf_smoothing:   float = 0.0,
    rbf_anchoring:   bool  = True,
    # Delaunay params
    delaunay_method: Literal["linear", "cubic"] = "linear",
    delaunay_fill:   bool  = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Chạy spatial interpolation trên regular grid.

    Returns:
        (grid_lats, grid_lngs, predicted_rssi, uncertainty)
        Tất cả là numpy arrays độ dài N (N = số grid points).
    """
    arr_lat  = np.asarray(lats,  dtype=float)
    arr_lng  = np.asarray(lngs,  dtype=float)
    arr_rssi = np.asarray(rssis, dtype=float)

    la_min, la_max, lo_min, lo_max = bbox_with_padding(arr_lat, arr_lng)
    grid_lats, grid_lngs = make_grid(la_min, la_max, lo_min, lo_max, resolution_m)

    logger.info(
        "interpolate_start",
        extra={
            "method": method, "n_points": len(arr_lat),
            "grid_points": len(grid_lats), "resolution_m": resolution_m,
        },
    )

    # ── IDW ──────────────────────────────────────────────────────────────────
    if method == "idw":
        elev_known = elev_grid = None
        use_elev = False
        try:
            dem = get_dem()
            if dem.tiles:
                elev_known = dem.get_elevations_batch(arr_lat.tolist(), arr_lng.tolist())
                elev_grid  = dem.get_elevations_batch(grid_lats.tolist(), grid_lngs.tolist())
                use_elev = True
                logger.info("idw_dem_enabled", extra={
                    "elev_min": float(elev_known.min()),
                    "elev_max": float(elev_known.max()),
                })
        except Exception as e:
            logger.warning("dem_skipped", extra={"reason": str(e)})

        return grid_lats, grid_lngs, *_idw(
            arr_lat, arr_lng, arr_rssi, grid_lats, grid_lngs,
            idw_power, idw_neighbors,
            use_elevation=use_elev, elev_known=elev_known, elev_grid=elev_grid,
        )

    # ── Kriging ───────────────────────────────────────────────────────────────
    if method == "kriging":
        return grid_lats, grid_lngs, *_kriging(
            arr_lat, arr_lng, arr_rssi, grid_lats, grid_lngs, kriging_model,
        )

    # ── RBF ───────────────────────────────────────────────────────────────────
    if method == "rbf":
        return grid_lats, grid_lngs, *_rbf(
            arr_lat, arr_lng, arr_rssi, grid_lats, grid_lngs,
            kernel=rbf_function,
            anchoring=rbf_anchoring,
            smoothing=rbf_smoothing,
        )

    # ── Delaunay ──────────────────────────────────────────────────────────────
    if method == "delaunay":
        return grid_lats, grid_lngs, *_delaunay(
            arr_lat, arr_lng, arr_rssi, grid_lats, grid_lngs,
            method=delaunay_method,
            fill_outside=delaunay_fill,
        )

    raise ValueError(
        f"Unknown interpolation method '{method}'. "
        f"Available: idw, kriging, rbf, delaunay"
    )
