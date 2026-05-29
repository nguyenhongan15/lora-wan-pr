"""So sánh 4 phương án xử lý DSM cho min-SF map (PoC gw 7276ff002e0507da).

Variants:
  - Baseline: DSM tile gốc (Stage B+D baked in), profile sample 30 m.
  - A: bỏ DSM hoàn toàn, chỉ DTM.
  - B: DSM clip excess ≤ 10 m (DTM + min(DSM-DTM, 10)), profile sample 30 m.
  - C: DSM gốc nhưng profile sample 100 m thay vì 30.

Mỗi variant chạy lại sim trên 7 cell test, in PL_dB + delta vs baseline.

Note: dùng tile danang only (`copernicus_glo30_danang.tif`) → KHÔNG đụng
production tile. B build tile tạm ở `tmp/dsm_clip10/`.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np
import rasterio

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "api-service" / "src"))

from crc_covlib import simulation as covlib  # noqa: E402

GW_LAT = 16.0740935
GW_LON = 108.1524913
ANTENNA_HEIGHT_M = 25.0
FREQ_MHZ = 923.2
RX_HEIGHT_M = 1.5

DEM_DIR = os.environ.get("LORA_DEM_DIRECTORY", "E:/DATN/lora-data/dem")
SURFACE_DEM_DIR = os.environ.get(
    "LORA_SURFACE_DEM_DIRECTORY", "E:/DATN/lora-data/dem-surface"
)

CLIP_EXCESS_M = 10.0
TMP_DIR = REPO_ROOT / "tmp" / "dsm_clip10"
TMP_H_DIR = REPO_ROOT / "tmp" / "dsm_built_up_only"
LANDCOVER_TILE = Path(
    "E:/DATN/lora-data/landcover/esa-worldcover/ESA_WorldCover_10m_2021_v200_N15E108_Map.tif"
)
ESA_BUILT_UP_CLASS = 50


def build_clipped_dsm() -> Path:
    """B: tạo DSM_clipped = DTM + min(DSM-DTM, 10), ghi vào TMP_DIR."""
    src_dsm = Path(SURFACE_DEM_DIR) / "copernicus_glo30_danang.tif"
    src_dtm = Path(DEM_DIR) / "copernicus_glo30_danang.tif"
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TMP_DIR / "copernicus_glo30_danang.tif"

    with rasterio.open(src_dsm) as dsm_ds, rasterio.open(src_dtm) as dtm_ds:
        dsm = dsm_ds.read(1).astype(np.float32)
        dtm = dtm_ds.read(1).astype(np.float32)
        if dsm.shape != dtm.shape:
            raise RuntimeError(f"shape mismatch: DSM {dsm.shape} vs DTM {dtm.shape}")
        excess = dsm - dtm
        clipped_excess = np.clip(excess, 0.0, CLIP_EXCESS_M)
        clipped_dsm = (dtm + clipped_excess).astype(dsm_ds.dtypes[0])
        profile = dsm_ds.profile.copy()
        with rasterio.open(out_path, "w", **profile) as out_ds:
            out_ds.write(clipped_dsm, 1)

    n_clipped = int(np.sum(excess > CLIP_EXCESS_M))
    pct = 100.0 * n_clipped / excess.size
    p99 = float(np.percentile(excess, 99))
    print(f"[B] DSM clipped: {n_clipped:,}/{excess.size:,} pixel ({pct:.2f}%) "
          f"capped, original p99={p99:.1f}m -> {CLIP_EXCESS_M:.0f}m. "
          f"Tile -> {out_path}")
    return TMP_DIR


def build_built_up_only_dsm() -> Path:
    """H: DSM = DTM ở mọi pixel KHÔNG phải built-up (class 50). Built-up giữ DSM gốc.

    Reproject ESA WorldCover (10m, EPSG:4326) sang grid DTM/DSM (30m) bằng
    nearest neighbor. Pixel built-up giữ DSM original (Stage D building bake);
    pixel khác (cây, water, cropland) set DSM = DTM (loại canopy/clutter excess).
    """
    from rasterio.warp import Resampling, reproject

    src_dsm = Path(SURFACE_DEM_DIR) / "copernicus_glo30_danang.tif"
    src_dtm = Path(DEM_DIR) / "copernicus_glo30_danang.tif"
    TMP_H_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TMP_H_DIR / "copernicus_glo30_danang.tif"

    with rasterio.open(src_dsm) as dsm_ds, rasterio.open(src_dtm) as dtm_ds, \
            rasterio.open(LANDCOVER_TILE) as lc_ds:
        dsm = dsm_ds.read(1).astype(np.float32)
        dtm = dtm_ds.read(1).astype(np.float32)

        lc_resampled = np.zeros(dsm.shape, dtype=np.uint8)
        reproject(
            source=rasterio.band(lc_ds, 1),
            destination=lc_resampled,
            src_transform=lc_ds.transform,
            src_crs=lc_ds.crs,
            dst_transform=dsm_ds.transform,
            dst_crs=dsm_ds.crs,
            resampling=Resampling.nearest,
        )

        built_up_mask = lc_resampled == ESA_BUILT_UP_CLASS
        out = np.where(built_up_mask, dsm, dtm).astype(dsm_ds.dtypes[0])

        profile = dsm_ds.profile.copy()
        with rasterio.open(out_path, "w", **profile) as out_ds:
            out_ds.write(out, 1)

    n_built = int(built_up_mask.sum())
    pct = 100.0 * n_built / built_up_mask.size
    print(f"[H] Built-up pixel: {n_built:,}/{built_up_mask.size:,} ({pct:.2f}%) "
          f"keep DSM, else set DSM=DTM. Tile -> {out_path}")
    return TMP_H_DIR


def _offset(lat: float, lon: float, dist_km: float, bearing_deg: float) -> tuple[float, float]:
    dlat = dist_km / 111.32 * math.cos(math.radians(bearing_deg))
    dlon = dist_km / (111.32 * math.cos(math.radians(lat))) * math.sin(math.radians(bearing_deg))
    return lat + dlat, lon + dlon


def make_sim(variant: str, clipped_dsm_dir: Path, built_up_dsm_dir: Path) -> covlib.Simulation:
    sim = covlib.Simulation()
    sim.SetTransmitterLocation(GW_LAT, GW_LON)
    sim.SetTransmitterHeight(ANTENNA_HEIGHT_M)
    sim.SetTransmitterFrequency(FREQ_MHZ)
    sim.SetTransmitterPower(0.1, covlib.PowerType.EIRP)
    sim.SetReceiverHeightAboveGround(RX_HEIGHT_M)
    sim.SetPropagationModel(covlib.PropagationModel.ITU_R_P_1812)
    sim.SetITURP1812TimePercentage(50.0)
    sim.SetITURP1812LocationPercentage(50.0)
    sim.SetPrimaryTerrainElevDataSource(covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF)
    sim.SetTerrainElevDataSourceDirectory(
        covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF, DEM_DIR
    )
    sim.SetResultType(covlib.ResultType.PATH_LOSS_DB)

    if variant == "baseline":
        sim.SetITURP1812SurfaceProfileMethod(
            covlib.P1812SurfaceProfileMethod.P1812_USE_SURFACE_ELEV_DATA
        )
        sim.SetPrimarySurfaceElevDataSource(covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF)
        sim.SetSurfaceElevDataSourceDirectory(
            covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF, SURFACE_DEM_DIR
        )
        sim.SetTerrainElevDataSamplingResolution(30)
    elif variant == "A_no_dsm":
        # KHÔNG set SurfaceProfileMethod / SurfaceElevDataSource → DTM-only
        sim.SetTerrainElevDataSamplingResolution(30)
    elif variant == "B_clip10":
        sim.SetITURP1812SurfaceProfileMethod(
            covlib.P1812SurfaceProfileMethod.P1812_USE_SURFACE_ELEV_DATA
        )
        sim.SetPrimarySurfaceElevDataSource(covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF)
        sim.SetSurfaceElevDataSourceDirectory(
            covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF, str(clipped_dsm_dir)
        )
        sim.SetTerrainElevDataSamplingResolution(30)
    elif variant == "C_sample100":
        sim.SetITURP1812SurfaceProfileMethod(
            covlib.P1812SurfaceProfileMethod.P1812_USE_SURFACE_ELEV_DATA
        )
        sim.SetPrimarySurfaceElevDataSource(covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF)
        sim.SetSurfaceElevDataSourceDirectory(
            covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF, SURFACE_DEM_DIR
        )
        sim.SetTerrainElevDataSamplingResolution(100)
    elif variant == "H_built_up":
        sim.SetITURP1812SurfaceProfileMethod(
            covlib.P1812SurfaceProfileMethod.P1812_USE_SURFACE_ELEV_DATA
        )
        sim.SetPrimarySurfaceElevDataSource(covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF)
        sim.SetSurfaceElevDataSourceDirectory(
            covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF, str(built_up_dsm_dir)
        )
        sim.SetTerrainElevDataSamplingResolution(30)
    else:
        raise ValueError(variant)
    return sim


def main() -> int:
    clipped_dir = build_clipped_dsm()
    built_up_dir = build_built_up_only_dsm()

    test_points = [
        ("gw_itself",        GW_LAT, GW_LON),
        ("0.5km_N",          *_offset(GW_LAT, GW_LON, 0.5, 0.0)),
        ("1km_W_built_up",   *_offset(GW_LAT, GW_LON, 1.0, 270.0)),
        ("3km_W",            *_offset(GW_LAT, GW_LON, 3.0, 270.0)),
        ("5km_S",            *_offset(GW_LAT, GW_LON, 5.0, 180.0)),
        ("7km_SW",           *_offset(GW_LAT, GW_LON, 7.0, 225.0)),
        ("10km_W",           *_offset(GW_LAT, GW_LON, 10.0, 270.0)),
    ]

    variants = ["baseline", "A_no_dsm", "B_clip10", "C_sample100", "H_built_up"]
    pl: dict[str, dict[str, float]] = {v: {} for v in variants}
    for v in variants:
        sim = make_sim(v, clipped_dir, built_up_dir)
        for name, lat, lon in test_points:
            try:
                detail = sim.GenerateReceptionPointDetailedResult(lat, lon)
                pl[v][name] = float(detail.pathLoss_dB)
            except Exception as exc:
                pl[v][name] = float("nan")
                print(f"  [{v}] {name}: ERROR {exc}")
        sim.Release()

    print()
    print(f"{'cell':<18} {'d_km':>5} " + " ".join(f"{v:>11}" for v in variants)
          + "    " + " ".join(f"d_{v[:6]:>9}" for v in variants if v != "baseline"))
    print("-" * 130)
    for name, lat, lon in test_points:
        d_km = math.sqrt(((lat - GW_LAT) * 111.32) ** 2
                         + ((lon - GW_LON) * 111.32 * math.cos(math.radians(GW_LAT))) ** 2)
        row = f"{name:<18} {d_km:>5.2f} "
        row += " ".join(f"{pl[v][name]:>11.2f}" for v in variants)
        base = pl["baseline"][name]
        row += "    " + " ".join(
            f"{pl[v][name] - base:>+11.2f}" for v in variants if v != "baseline"
        )
        print(row)

    return 0


if __name__ == "__main__":
    sys.exit(main())
