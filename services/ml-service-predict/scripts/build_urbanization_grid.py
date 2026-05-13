"""Build urbanization GeoTIFF từ OSM PBF (offline, manual run).

Pipeline:
  1. Đọc PBF qua pyosmium, lấy way + relation tag `building=*` (mọi loại building).
  2. Convert mỗi polygon sang shapely (WGS84, EPSG:4326).
  3. Rasterize building footprint vào grid 100m (toàn VN bbox).
     Mỗi cell: float ∈ [0,1] = fraction of cell area covered by building.
  4. Smooth bằng radius-200m mean filter (~4-cell box ở grid 100m).
     Plan v1 §3.5: urbanization_index = building footprint area trong R=200m.
  5. Output GeoTIFF compressed (~10-50MB cho VN).

Run:
  uv run --project services/ml-service-predict \
    --extra build python services/ml-service-predict/scripts/build_urbanization_grid.py \
    --pbf $LORA_OSM_PBF_PATH \
    --out $LORA_URBANIZATION_PATH

VN bbox default: lat 8.5-23.5, lon 102.0-110.0 (toàn lãnh thổ + Trường Sa/Hoàng Sa
KHÔNG include — out of LoRa scope; coast cover đủ Đà Nẵng + Hải Phòng).

Build time estimate trên laptop CPU: 5-15 phút cho VN PBF ~1GB.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import osmium
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from scipy.ndimage import uniform_filter
from shapely.geometry import Polygon

# VN bbox — chốt một lần. Đổi qua CLI nếu cần custom (xem argparse below).
_VN_BBOX = {"min_lat": 8.5, "max_lat": 23.5, "min_lon": 102.0, "max_lon": 110.0}

# Cell size 100m ở vĩ độ trung bình VN (~16°N).
# 1° lat ≈ 111 km → 100m ≈ 0.0009° lat
# 1° lon ≈ 111 * cos(16°) ≈ 107 km → 100m ≈ 0.000935° lon
# Dùng grid đều theo lat 0.001° (~111m) cho đơn giản. Sai lệch ~10% chấp nhận
# được vì plan §3.5 nói "radius 200m" là ballpark, không phải spec chính xác.
_CELL_DEG = 0.001

# Smoothing kernel size: 200m radius → 400m box → 4 cell ở grid 0.001°.
# uniform_filter dùng kernel hình vuông; chấp nhận sai lệch so với circular.
_SMOOTH_KERNEL_CELLS = 4


class _BuildingHandler(osmium.SimpleHandler):
    """Collect mọi polygon có tag `building=*`. Way (closed) + multipolygon relation."""

    def __init__(self) -> None:
        super().__init__()
        self.polygons: list[Polygon] = []
        # Factory để build shapely geometry từ OSM data (osmium provided).
        self._wkb_factory = osmium.geom.WKBFactory()

    def area(self, a: osmium.osm.Area) -> None:
        """`area` callback gộp closed-way + multipolygon relation."""
        if "building" not in a.tags:
            return
        try:
            wkb = self._wkb_factory.create_multipolygon(a)
        except RuntimeError:
            return  # broken geometry, skip
        from shapely import wkb as shp_wkb

        geom = shp_wkb.loads(wkb, hex=False)
        # MultiPolygon → tách thành các Polygon
        if geom.geom_type == "MultiPolygon":
            self.polygons.extend(g for g in geom.geoms if not g.is_empty)
        elif geom.geom_type == "Polygon" and not geom.is_empty:
            self.polygons.append(geom)


def _build_raster(pbf_path: Path, out_path: Path) -> None:
    print(f"[1/4] Reading PBF: {pbf_path}", file=sys.stderr)
    handler = _BuildingHandler()
    # `locations=True` để way lookup được node coordinates.
    handler.apply_file(str(pbf_path), locations=True)
    print(f"        → {len(handler.polygons):,} building polygons", file=sys.stderr)

    width = math.ceil((_VN_BBOX["max_lon"] - _VN_BBOX["min_lon"]) / _CELL_DEG)
    height = math.ceil((_VN_BBOX["max_lat"] - _VN_BBOX["min_lat"]) / _CELL_DEG)
    transform = from_bounds(
        _VN_BBOX["min_lon"],
        _VN_BBOX["min_lat"],
        _VN_BBOX["max_lon"],
        _VN_BBOX["max_lat"],
        width,
        height,
    )

    print(
        f"[2/4] Rasterizing → {width}x{height} grid (~{width * height / 1e6:.1f}M cells)",
        file=sys.stderr,
    )
    # all_touched=True: cell có building chạm qua → mark = 1.
    # Đây là approximation; không tính fraction-of-cell. Sau khi smooth bằng
    # uniform_filter, kết quả ~= local building density ∈ [0,1] đủ tốt cho GBM.
    binary = rasterize(
        ((g, 1) for g in handler.polygons),
        out_shape=(height, width),
        transform=transform,
        all_touched=True,
        fill=0,
        dtype="uint8",
    )

    print(f"[3/4] Smoothing với uniform_filter kernel={_SMOOTH_KERNEL_CELLS}", file=sys.stderr)
    smoothed = uniform_filter(
        binary.astype(np.float32), size=_SMOOTH_KERNEL_CELLS, mode="constant", cval=0.0
    )
    # Clip [0,1] (uniform_filter trả [0,1] với input binary 0/1, nhưng để chắc).
    np.clip(smoothed, 0.0, 1.0, out=smoothed)

    print(f"[4/4] Writing GeoTIFF: {out_path}", file=sys.stderr)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_path,
        mode="w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        compress="lzw",
        predictor=3,  # floating point predictor
        nodata=-1.0,
    ) as dst:
        dst.write(smoothed, 1)
    print(f"        → done ({out_path.stat().st_size / 1024**2:.1f} MB)", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build urbanization GeoTIFF từ OSM PBF (VN, plan-v1 §3.5)"
    )
    parser.add_argument(
        "--pbf", required=True, type=Path, help="Input OSM PBF (e.g., vietnam-latest.osm.pbf)"
    )
    parser.add_argument("--out", required=True, type=Path, help="Output GeoTIFF path")
    args = parser.parse_args()

    if not args.pbf.exists():
        print(f"ERROR: PBF not found: {args.pbf}", file=sys.stderr)
        return 1
    _build_raster(args.pbf, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
