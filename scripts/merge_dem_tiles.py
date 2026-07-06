"""Merge các tile Copernicus GLO-30 COG thành 1 GeoTIFF crop theo bbox.

Dùng bởi setup.sh (chạy trong container celery-worker, image có rasterio):
tile thô tải từ AWS đặt tên Copernicus_DSM_COG_10_*_DEM.tif; pipeline retrain
(scripts/build_training_csv.py) lại kỳ vọng ĐÚNG tên file
/data/dem/copernicus_glo30_danang.tif — script này tạo ra file đó, bounds
truyền từ setup.sh khớp từng pixel với file gốc trên máy dev.

Usage:
    python scripts/merge_dem_tiles.py \
        --src-dir /data-rw/dem-raw \
        --out /data-rw/dem/copernicus_glo30_danang.tif \
        --bounds 107.9 15.8 108.5 16.3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import rasterio
from rasterio.merge import merge


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src-dir", required=True, help="Thư mục chứa tile *.tif nguồn")
    parser.add_argument("--out", required=True, help="Đường dẫn GeoTIFF output")
    parser.add_argument(
        "--bounds",
        nargs=4,
        type=float,
        metavar=("LEFT", "BOTTOM", "RIGHT", "TOP"),
        required=True,
        help="Bbox crop (lon_min lat_min lon_max lat_max, WGS84)",
    )
    args = parser.parse_args()

    tiles = sorted(Path(args.src_dir).glob("*.tif"))
    if not tiles:
        print(f"ERROR: không có *.tif trong {args.src_dir}", file=sys.stderr)
        return 1

    sources = [rasterio.open(p) for p in tiles]
    try:
        array, transform = merge(sources, bounds=tuple(args.bounds))
        meta = sources[0].meta.copy()
        meta.update(
            driver="GTiff",
            height=array.shape[1],
            width=array.shape[2],
            transform=transform,
            compress="deflate",
        )
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        # Ghi file tạm rồi rename — tránh để lại file dở khi bị ngắt giữa chừng
        # (setup.sh check idempotent bằng sự tồn tại của file đích).
        tmp = out.with_suffix(".tif.tmp")
        with rasterio.open(tmp, "w", **meta) as dst:
            dst.write(array)
        tmp.replace(out)
    finally:
        for src in sources:
            src.close()

    print(f"OK: merge {len(tiles)} tile -> {args.out} ({array.shape[2]}x{array.shape[1]} px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
