"""So sánh GHSL GHS-BUILT-H 2018 (R2023A) vs Stage D building bake (DSM-DTM).

- GHSL: 100m raster, average building height per cell, Mollweide ESRI:54009.
  Tile R8_C29 cover Đà Nẵng bbox.
- Stage D: bake Google Buildings v3 vào DSM raster Copernicus GLO-30 (30m,
  EPSG:4326). Excess = DSM - DTM = approx building/canopy height.

Mỗi test cell quanh gw 0507da: lấy GHSL height vs Stage D excess. Cũng scan
1 patch 5×5 km quanh Đà Nẵng center → correlation + delta histogram.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
import rasterio.warp

REPO_ROOT = Path(__file__).resolve().parent.parent

GHSL_TILE = (
    REPO_ROOT / "tmp" / "ghsl" / "GHS_BUILT_H_AGBH_E2018_GLOBE_R2023A_54009_100_V1_0_R8_C29.tif"
)
STAGED_DSM = Path("E:/DATN/lora-data/dem-surface/copernicus_glo30_danang.tif")
DTM = Path("E:/DATN/lora-data/dem/copernicus_glo30_danang.tif")

GW_LAT = 16.0740935
GW_LON = 108.1524913


def _offset(lat: float, lon: float, dist_km: float, bearing_deg: float) -> tuple[float, float]:
    dlat = dist_km / 111.32 * math.cos(math.radians(bearing_deg))
    dlon = dist_km / (111.32 * math.cos(math.radians(lat))) * math.sin(math.radians(bearing_deg))
    return lat + dlat, lon + dlon


def sample_raster(ds: rasterio.DatasetReader, lat: float, lon: float, dst_crs) -> float:
    if str(dst_crs) != "EPSG:4326":
        xs, ys = rasterio.warp.transform("EPSG:4326", dst_crs, [lon], [lat])
        x, y = xs[0], ys[0]
    else:
        x, y = lon, lat
    row, col = ds.index(x, y)
    if row < 0 or col < 0 or row >= ds.height or col >= ds.width:
        return float("nan")
    arr = ds.read(1, window=((row, row + 1), (col, col + 1)))
    v = float(arr[0, 0])
    if ds.nodata is not None and v == ds.nodata:
        return float("nan")
    return v


def main() -> int:
    test_points = [
        ("gw_itself", GW_LAT, GW_LON),
        ("0.5km_N", *_offset(GW_LAT, GW_LON, 0.5, 0.0)),
        ("1km_W_built_up", *_offset(GW_LAT, GW_LON, 1.0, 270.0)),
        ("3km_W", *_offset(GW_LAT, GW_LON, 3.0, 270.0)),
        ("5km_S", *_offset(GW_LAT, GW_LON, 5.0, 180.0)),
        ("7km_SW", *_offset(GW_LAT, GW_LON, 7.0, 225.0)),
        ("10km_W", *_offset(GW_LAT, GW_LON, 10.0, 270.0)),
    ]

    with (
        rasterio.open(GHSL_TILE) as ghsl_ds,
        rasterio.open(STAGED_DSM) as dsm_ds,
        rasterio.open(DTM) as dtm_ds,
    ):
        print("== Per-cell comparison ==")
        print(
            f"{'cell':<18} {'lat':>10} {'lon':>10} {'GHSL_h':>8} {'StageD_excess':>14} {'diff':>7}"
        )
        print("-" * 75)
        for name, lat, lon in test_points:
            ghsl_h = sample_raster(ghsl_ds, lat, lon, ghsl_ds.crs)
            dsm_v = sample_raster(dsm_ds, lat, lon, dsm_ds.crs)
            dtm_v = sample_raster(dtm_ds, lat, lon, dtm_ds.crs)
            excess = (
                dsm_v - dtm_v if math.isfinite(dsm_v) and math.isfinite(dtm_v) else float("nan")
            )
            diff = (
                ghsl_h - excess if math.isfinite(ghsl_h) and math.isfinite(excess) else float("nan")
            )
            print(
                f"{name:<18} {lat:>10.5f} {lon:>10.5f} {ghsl_h:>8.2f} {excess:>14.2f} {diff:>7.2f}"
            )

        # ── Patch-level statistics ─────────────────────────────────────────
        print()
        print("== Patch stats: 10 x 10 km centred on gw 0507da ==")

        half_deg = 0.045  # ~5km lat
        n = 100  # 100x100 sample grid
        lats = np.linspace(GW_LAT - half_deg, GW_LAT + half_deg, n)
        lons = np.linspace(GW_LON - half_deg, GW_LON + half_deg, n)

        ghsl_arr = np.full((n, n), np.nan, dtype=np.float32)
        excess_arr = np.full((n, n), np.nan, dtype=np.float32)

        for i, la in enumerate(lats):
            for j, lo in enumerate(lons):
                ghsl_arr[i, j] = sample_raster(ghsl_ds, la, lo, ghsl_ds.crs)
                dsm_v = sample_raster(dsm_ds, la, lo, dsm_ds.crs)
                dtm_v = sample_raster(dtm_ds, la, lo, dtm_ds.crs)
                if math.isfinite(dsm_v) and math.isfinite(dtm_v):
                    excess_arr[i, j] = dsm_v - dtm_v

        ghsl_arr = np.where(ghsl_arr < 0, 0.0, ghsl_arr)  # GHSL có thể có 0 hoặc nodata
        excess_arr = np.clip(excess_arr, 0, None)

        m = np.isfinite(ghsl_arr) & np.isfinite(excess_arr)
        a, b = ghsl_arr[m], excess_arr[m]
        print(f"  Pixels sampled: {m.sum()}/{m.size}")
        print(
            f"  GHSL building height  : mean={a.mean():.2f} m, p50={np.median(a):.2f}, "
            f"p90={np.percentile(a, 90):.2f}, p99={np.percentile(a, 99):.2f}, max={a.max():.2f}"
        )
        print(
            f"  Stage D excess        : mean={b.mean():.2f} m, p50={np.median(b):.2f}, "
            f"p90={np.percentile(b, 90):.2f}, p99={np.percentile(b, 99):.2f}, max={b.max():.2f}"
        )
        if a.std() > 1e-3 and b.std() > 1e-3:
            corr = np.corrcoef(a, b)[0, 1]
            print(f"  Pearson correlation   : r = {corr:.3f}")
        nonzero_ghsl = (a > 0.5).sum()
        nonzero_excess = (b > 0.5).sum()
        print(
            f"  Pixels with GHSL h > 0.5m   : {nonzero_ghsl} ({100 * nonzero_ghsl / len(a):.1f}%)"
        )
        print(
            f"  Pixels with StageD ex > 0.5m: {nonzero_excess} ({100 * nonzero_excess / len(b):.1f}%)"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
