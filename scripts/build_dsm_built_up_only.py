"""Build DSM_built_up_only: giữ DSM raster gốc ở pixel built-up (ESA WorldCover
class 50), set DSM = DTM ở mọi pixel khác (vegetation/water/cropland/etc).

Mục đích: crc-covlib P.1812 sample profile chỉ "thấy" building diffraction
trong vùng đô thị thực, không bị artifact Stage B canopy fill (default 9m)
ở vùng rural. Đã spike validate vs GHSL 2018 (mean 0.74m ngoài built-up,
xác nhận canopy fill 9m là artifact).

Usage:
    uv run python scripts/build_dsm_built_up_only.py \
        --dsm  E:/DATN/lora-data/dem-surface/copernicus_glo30_danang.tif \
        --dtm  E:/DATN/lora-data/dem/copernicus_glo30_danang.tif \
        --lc   E:/DATN/lora-data/landcover/esa-worldcover/ESA_WorldCover_10m_2021_v200_N15E108_Map.tif \
        --out  E:/DATN/lora-data/dem-surface-built-up-only/copernicus_glo30_danang.tif
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

ESA_BUILT_UP_CLASS = 50


def build(dsm_path: Path, dtm_path: Path, lc_path: Path, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with (
        rasterio.open(dsm_path) as dsm_ds,
        rasterio.open(dtm_path) as dtm_ds,
        rasterio.open(lc_path) as lc_ds,
    ):
        dsm = dsm_ds.read(1).astype(np.float32)
        dtm = dtm_ds.read(1).astype(np.float32)

        if dsm.shape != dtm.shape:
            raise RuntimeError(f"DSM/DTM shape mismatch: {dsm.shape} vs {dtm.shape}")

        # Reproject ESA WorldCover (10m, 4326) lên grid DSM (30m, 4326). Đà Nẵng
        # tile nằm trọn trong N15E108 → nearest-neighbor đủ.
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

    n = int(built_up_mask.sum())
    pct = 100.0 * n / built_up_mask.size
    print(f"Built-up pixel: {n:,}/{built_up_mask.size:,} ({pct:.2f}%) keep DSM.")
    print(f"Wrote {out_path} ({out_path.stat().st_size:,} bytes)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dsm", required=True, type=Path)
    p.add_argument("--dtm", required=True, type=Path)
    p.add_argument("--lc", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    build(a.dsm, a.dtm, a.lc, a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
