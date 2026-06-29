"""Cấu hình ITU-R P.1812 + P.2108 DÙNG CHUNG cho 2 đường physics.

Trước đây `CrcCovlibBackend` (/predict) và `scripts/precompute_rssi_heatmap.py`
(heatmap) lặp y hệt phần setup crc-covlib Simulation + logic clutter P.2108 →
dễ drift (đã từng lệch location% + bias). Gom về đây làm một nguồn sự thật:

  - `configure_p1812_propagation(sim, ...)`: set propagation model + time/location
    %, surface-profile method, nguồn DEM/Surface, landcover clutter, result type,
    sampling. Caller TỰ set transmitter (location/height/freq/power) + receiver
    height + tự gọi `GenerateReceptionPointResult` (point cho backend, grid cho
    heatmap) — phần KHÁC nhau giữ ở caller.
  - `p2108_clutter_db(...)`: suy hao clutter thống kê P.2108-1, gate có-DSM +
    khoảng cách tối thiểu (tránh double-count khi đã có surface DEM).

crc-covlib import lazy bên trong hàm để module import được ở môi trường chưa cài
lib (vd CI unit-test collection).
"""

from __future__ import annotations

from typing import Any

# DEM sampling 30 m khớp Copernicus GLO-30 cell size.
DEM_SAMPLING_RESOLUTION_M = 30
# P.2108-1 §3.2 chỉ valid cho 0.25 ≤ d ≤ 100 km; dưới 0.25 km clutter không đáng
# kể so với free-space + diffraction P.1812 đã tính.
P2108_MIN_DISTANCE_KM = 0.25


def configure_p1812_propagation(
    sim: Any,
    *,
    time_pct: float,
    loc_pct: float,
    dem_dir: str,
    surface_dir: str | None,
    landcover_dir: str | None = None,
) -> None:
    """Cấu hình 1 crc-covlib Simulation cho P.1812 (KHÔNG đụng transmitter/receiver).

    `surface_dir` rỗng/None → dùng `dem_dir` làm surface source (DTM-only). Khi
    set → P.1812 model nhiễu xạ qua surface thật (building/canopy); caller nên tắt
    P.2108 tương ứng (xem `p2108_clutter_db(has_surface=...)`).
    """
    from crc_covlib import simulation as covlib  # type: ignore[import-untyped]

    sim.SetPropagationModel(covlib.PropagationModel.ITU_R_P_1812)
    sim.SetITURP1812TimePercentage(time_pct)
    sim.SetITURP1812LocationPercentage(loc_pct)
    sim.SetITURP1812SurfaceProfileMethod(
        covlib.P1812SurfaceProfileMethod.P1812_USE_SURFACE_ELEV_DATA
    )
    sim.SetPrimaryTerrainElevDataSource(covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF)
    sim.SetTerrainElevDataSourceDirectory(
        covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF, str(dem_dir)
    )
    sim.SetPrimarySurfaceElevDataSource(covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF)
    sim.SetSurfaceElevDataSourceDirectory(
        covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF, str(surface_dir or dem_dir)
    )
    if landcover_dir:
        from .landcover_mapping import apply_esa_worldcover_mapping

        apply_esa_worldcover_mapping(sim, str(landcover_dir))
    sim.SetResultType(covlib.ResultType.PATH_LOSS_DB)
    sim.SetTerrainElevDataSamplingResolution(DEM_SAMPLING_RESOLUTION_M)


def p2108_clutter_db(
    freq_mhz: float, dist_km: float, loc_pct: float, *, has_surface: bool
) -> float:
    """ITU-R P.2108-1 terrestrial clutter loss (dB).

    `has_surface=True` (đang dùng DSM) → 0.0: P.1812 đã model nhiễu xạ qua
    surface, cộng P.2108 nữa = double-count (verify 2026-05-31: +24-26 dB sai).
    DTM-only → trả P.2108 statistic, gate khoảng cách ≥ 0.25 km.
    """
    if has_surface or dist_km < P2108_MIN_DISTANCE_KM:
        return 0.0
    from crc_covlib.helper import itur_p2108  # type: ignore[import-untyped]

    return float(itur_p2108.TerrestrialPathClutterLoss(freq_mhz / 1000.0, dist_km, loc_pct))
