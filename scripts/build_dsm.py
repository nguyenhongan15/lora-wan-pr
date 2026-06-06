"""Build Digital Surface Model (DSM) GeoTIFF tiles từ DTM + OSM buildings.

Pipeline (per terrain tile):
  1. Open input terrain DEM (Copernicus GLO-30), lấy bounds + transform + array.
  2. Scan OSM PBF, collect polygons có tag `building=*` intersect tile bbox.
  3. Parse height per building từ tag (height, building:levels) + type fallback.
  4. Rasterize building heights vào grid khớp terrain (sort ascending để cell
     có overlap thì tòa cao hơn ghi đè — đúng physics: P.1812 thấy đỉnh cao nhất).
  5. surface = terrain + building_height (cell nào không có building → height=0).
  6. Write GeoTIFF cùng transform/CRS/dtype với input.

DSM dùng cho crc-covlib P.1812 với `P1812_USE_SURFACE_ELEV_DATA=True`. Khác DTM:
  - DTM = mặt đất (terrain only) — default Copernicus GLO-30
  - DSM = đỉnh nhà/cây (surface) — DTM + building heights

LoRa diffraction ở 920 MHz qua rooftop khoảng 5-15 dB tùy hình học. Dùng DSM
giảm overestimate range của Stage 1 ở khu đô thị đặc (paper Fig 11 style).

Run:
    uv run --project services/api-service python scripts/build_dsm.py
    uv run --project services/api-service python scripts/build_dsm.py \
        --dem-dir E:/DATN/lora-data/dem \
        --pbf E:/DATN/lora-data/osm/vietnam-260512.osm.pbf \
        --out-dir E:/DATN/lora-data/dem-surface

Time estimate: ~5-10 phút (PBF scan 30s/tile × 3 tiles + rasterization).

Sau khi xong, point crc-covlib backend sang `dem-surface/` thay vì `dem/`
(hoặc dùng 2 dir riêng nếu muốn switch DTM/DSM mode).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import osmium
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from shapely.geometry import Polygon, box

log = logging.getLogger("build_dsm")

# Default height theo building type khi không có `height` / `building:levels`.
# Số liệu approximation cho Đà Nẵng / VN đô thị — không cần chính xác tuyệt đối
# vì P.1812 diffraction smooth dần theo height; sai 2-3m không ảnh hưởng SF band.
_TYPE_DEFAULTS_M: dict[str, float] = {
    # Nhà ở
    "house": 6.0,
    "detached": 6.0,
    "residential": 9.0,
    "terrace": 9.0,
    "bungalow": 4.0,
    "semi": 6.0,
    # Chung cư / khách sạn — thường tower
    "apartments": 30.0,
    "dormitory": 18.0,
    "hotel": 30.0,
    "hostel": 12.0,
    # Thương mại / dịch vụ
    "commercial": 15.0,
    "office": 24.0,
    "retail": 9.0,
    "supermarket": 9.0,
    "kiosk": 3.0,
    "shop": 6.0,
    # Công cộng
    "school": 12.0,
    "kindergarten": 6.0,
    "university": 18.0,
    "college": 15.0,
    "hospital": 24.0,
    "clinic": 9.0,
    "government": 18.0,
    "public": 12.0,
    "civic": 12.0,
    # Religious
    "church": 18.0,
    "cathedral": 30.0,
    "mosque": 18.0,
    "temple": 12.0,
    "pagoda": 15.0,
    "chapel": 9.0,
    "shrine": 6.0,
    # Industrial
    "industrial": 10.0,
    "warehouse": 10.0,
    "factory": 12.0,
    "manufacture": 12.0,
    # Phụ
    "garage": 3.0,
    "garages": 3.0,
    "carport": 3.0,
    "shed": 3.0,
    "hut": 3.0,
    "barn": 6.0,
    "stable": 4.0,
    "greenhouse": 4.0,
    "roof": 5.0,
    "construction": 6.0,
    # Generic OSM tag "building=yes" (không type cụ thể) — phổ biến nhất ở VN.
    "yes": 9.0,
}

# Default cuối cùng khi tag building=* có giá trị lạ không trong dict trên.
_FALLBACK_HEIGHT_M = 9.0


def _parse_explicit_height(tags: osmium.osm.TagList) -> float | None:
    """Đọc height từ tag `height` hoặc `building:levels`. Trả None nếu không có."""
    if "height" in tags:
        s = tags.get("height", "").strip().lower()
        # OSM dùng nhiều format: "12", "12 m", "12m", "12.5", "40'" (feet).
        # Strip unit thường gặp; bỏ feet (vì hiếm + không quan trọng accuracy).
        s = s.replace(" ", "").replace("m", "").replace("ft", "").replace("'", "")
        try:
            h = float(s)
            if 0 < h < 500:  # sanity: 0-500m
                return h
        except ValueError:
            pass
    if "building:levels" in tags:
        try:
            levels = float(tags.get("building:levels", "").strip())
            if 0 < levels < 200:
                # 3m / tầng = chuẩn VN (1 trệt + tầng = ~3-3.5m). Dùng 3.0 cho
                # đơn giản; sai số <10% với building <15 tầng.
                return levels * 3.0
        except ValueError:
            pass
    return None


def _building_height(tags: osmium.osm.TagList) -> float:
    """Resolve height cho 1 building. Ưu tiên tag explicit, fallback theo type."""
    h = _parse_explicit_height(tags)
    if h is not None:
        return h
    btype = tags.get("building", "yes").strip().lower()
    return _TYPE_DEFAULTS_M.get(btype, _FALLBACK_HEIGHT_M)


class _BuildingHandler(osmium.SimpleHandler):
    """Collect (polygon, height) cho building có centroid trong tile bbox.

    Filter by centroid để tránh đếm duplicate khi building chạm 2 tile (LoRa
    coverage scope per-tile riêng biệt, edge effects negligible).
    """

    def __init__(self, tile_bbox: tuple[float, float, float, float]):
        super().__init__()
        # (minx, miny, maxx, maxy) WGS84
        self.tile_bbox = tile_bbox
        self.tile_box = box(*tile_bbox)
        self.entries: list[tuple[Polygon, float]] = []
        self._wkb_factory = osmium.geom.WKBFactory()
        self._skipped_broken = 0

    def area(self, a: osmium.osm.Area) -> None:
        if "building" not in a.tags:
            return
        # Quick bbox reject trước khi build geometry — geometry build tốn CPU,
        # bbox check là O(1).
        try:
            env = a.envelope()
            if env is None:
                return
            # osmium envelope: bottom_left + top_right (Location objects)
            bl = env.bottom_left
            tr = env.top_right
            if (
                tr.lon < self.tile_bbox[0]
                or bl.lon > self.tile_bbox[2]
                or tr.lat < self.tile_bbox[1]
                or bl.lat > self.tile_bbox[3]
            ):
                return
        except Exception:
            pass

        try:
            wkb = self._wkb_factory.create_multipolygon(a)
        except RuntimeError:
            self._skipped_broken += 1
            return
        from shapely import wkb as shp_wkb

        geom = shp_wkb.loads(wkb, hex=False)
        height = _building_height(a.tags)

        # MultiPolygon → tách thành các Polygon (height dùng chung).
        polys: list[Polygon] = []
        if geom.geom_type == "MultiPolygon":
            polys.extend(g for g in geom.geoms if not g.is_empty)
        elif geom.geom_type == "Polygon" and not geom.is_empty:
            polys.append(geom)

        for p in polys:
            # Final precise filter qua centroid sau khi đã có geometry.
            if not self.tile_box.contains(p.centroid):
                continue
            self.entries.append((p, height))


def _build_dsm_for_tile(
    tile_path: Path,
    pbf_path: Path,
    out_path: Path,
    pixel_size_m: float | None = None,
) -> dict[str, float | int]:
    """Sinh 1 surface tile từ 1 terrain tile + buildings trong PBF.

    Nếu `pixel_size_m` set + khác native resolution, terrain được reproject
    sang grid mới (bilinear) trước khi rasterize buildings — giúp building
    polygon nhỏ < 30m hiện rõ ở DSM 10m / 5m.
    """
    t0 = time.time()
    with rasterio.open(tile_path) as src:
        terrain_native = src.read(1).astype(np.float32)
        native_transform = src.transform
        bounds = src.bounds
        nodata = src.nodata
        profile = src.profile.copy()
        src_crs = src.crs

    # Resample terrain to target pixel size if requested. Native GLO-30 = ~30m
    # (~0.000278° at equator); target 10m → ~0.0000926°. Bilinear resample đủ
    # smooth cho terrain (P.1812 nội suy profile DSM dọc tia tx→rx).
    if pixel_size_m is not None:
        native_pixel_m = abs(native_transform.a) * 111000.0  # rough deg→m at equator
        if abs(native_pixel_m - pixel_size_m) > 0.5:
            log.info(
                "[%s] resampling terrain %.1fm → %.1fm (bilinear)",
                tile_path.name,
                native_pixel_m,
                pixel_size_m,
            )
            target_deg = pixel_size_m / 111000.0
            new_nx = round((bounds.right - bounds.left) / target_deg)
            new_ny = round((bounds.top - bounds.bottom) / target_deg)
            new_transform = from_origin(bounds.left, bounds.top, target_deg, target_deg)
            terrain = np.zeros((new_ny, new_nx), dtype=np.float32)
            reproject(
                source=terrain_native,
                destination=terrain,
                src_transform=native_transform,
                src_crs=src_crs,
                dst_transform=new_transform,
                dst_crs=src_crs,
                resampling=Resampling.bilinear,
                src_nodata=nodata,
                dst_nodata=nodata if nodata is not None else 0,
            )
            transform = new_transform
            profile.update(width=new_nx, height=new_ny, transform=new_transform)
        else:
            terrain = terrain_native
            transform = native_transform
    else:
        terrain = terrain_native
        transform = native_transform

    log.info(
        "[%s] tile bounds (%.4f,%.4f)-(%.4f,%.4f) shape=%s",
        tile_path.name,
        bounds.left,
        bounds.bottom,
        bounds.right,
        bounds.top,
        terrain.shape,
    )

    log.info("[%s] scanning PBF for buildings in bbox...", tile_path.name)
    t1 = time.time()
    handler = _BuildingHandler((bounds.left, bounds.bottom, bounds.right, bounds.top))
    handler.apply_file(str(pbf_path), locations=True)
    pbf_elapsed = time.time() - t1
    log.info(
        "[%s] %d buildings collected (%.0fs PBF scan, %d broken skipped)",
        tile_path.name,
        len(handler.entries),
        pbf_elapsed,
        handler._skipped_broken,
    )

    if not handler.entries:
        log.warning("[%s] không có building trong bbox — DSM = terrain", tile_path.name)
        building_h = np.zeros_like(terrain)
    else:
        # Sort ascending theo height: rasterize sẽ overwrite trong order →
        # building cao ghi sau, đè lên building thấp. Cell overlap → max(height).
        entries_sorted = sorted(handler.entries, key=lambda e: e[1])
        shapes = ((p, h) for p, h in entries_sorted)
        log.info("[%s] rasterizing %d polygons...", tile_path.name, len(entries_sorted))
        t2 = time.time()
        # all_touched=True: nhà có cạnh chạm cell → cell được mark. Cần thiết
        # vì building VN thường 5-15m (nhỏ hơn cell 30m), all_touched=False sẽ
        # bỏ qua phần lớn building. Đánh đổi: cell edge có thể overestimate
        # nhẹ, nhưng physics-wise đúng hướng (conservative = nhiều shadowing).
        building_h = rasterize(
            shapes,
            out_shape=terrain.shape,
            transform=transform,
            fill=0.0,
            dtype="float32",
            all_touched=True,
        )
        log.info("[%s] rasterized in %.0fs", tile_path.name, time.time() - t2)

    # Combine: surface = terrain + building_height. Nodata pixel giữ nguyên.
    surface = terrain.copy()
    if nodata is not None:
        mask = terrain != nodata
        surface[mask] = terrain[mask] + building_h[mask]
    else:
        surface = terrain + building_h

    # Write output cùng profile như input (LZW compressed để giảm size).
    profile.update(
        dtype="float32",
        compress="lzw",
        predictor=3,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, mode="w", **profile) as dst:
        dst.write(surface, 1)

    n_buildings = len(handler.entries)
    pct_covered = float(np.count_nonzero(building_h) / building_h.size * 100)
    elapsed = time.time() - t0
    log.info(
        "[%s] done %.0fs — %d buildings, %.2f%% cells covered, mean h=%.1fm, max h=%.1fm",
        tile_path.name,
        elapsed,
        n_buildings,
        pct_covered,
        float(building_h[building_h > 0].mean()) if pct_covered > 0 else 0.0,
        float(building_h.max()),
    )
    return {
        "tile": tile_path.name,
        "buildings": n_buildings,
        "pct_cells_covered": pct_covered,
        "elapsed_s": elapsed,
    }


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dem-dir",
        type=Path,
        default=Path("E:/DATN/lora-data/dem"),
        help="Directory chứa terrain GeoTIFF tiles (Copernicus GLO-30)",
    )
    parser.add_argument(
        "--pbf",
        type=Path,
        default=Path("E:/DATN/lora-data/osm/vietnam-260512.osm.pbf"),
        help="OSM PBF (chứa building polygons + tags)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("E:/DATN/lora-data/dem-surface"),
        help="Output directory cho surface tiles (cùng filename như input)",
    )
    parser.add_argument(
        "--tile",
        type=str,
        default=None,
        help="Chỉ process 1 tile (filename). Default: tất cả .tif trong dem-dir",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute even if output already exists",
    )
    parser.add_argument(
        "--pixel-size-m",
        type=float,
        default=None,
        help=(
            "Output pixel size (mét). Default: giữ native (Copernicus GLO-30 ~30m). "
            "Set 10 để build DSM 10m — terrain bilinear upsample, building "
            "rasterize ở 10m grid."
        ),
    )
    args = parser.parse_args()

    if not args.dem_dir.is_dir():
        log.error("--dem-dir không tồn tại: %s", args.dem_dir)
        return 2
    if not args.pbf.is_file():
        log.error("--pbf không tồn tại: %s", args.pbf)
        return 2

    tiles = sorted(args.dem_dir.glob("*.tif"))
    if args.tile:
        tiles = [t for t in tiles if t.name == args.tile]
        if not tiles:
            log.error("Không tìm thấy tile: %s", args.tile)
            return 1
    if not tiles:
        log.error("Không có .tif trong %s", args.dem_dir)
        return 1
    log.info("Sẽ process %d tile: %s", len(tiles), [t.name for t in tiles])

    args.out_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    for tile in tiles:
        out_path = args.out_dir / tile.name
        if out_path.exists() and not args.force:
            log.info("[%s] skip (đã có %s, dùng --force để overwrite)", tile.name, out_path)
            continue
        summary.append(
            _build_dsm_for_tile(tile, args.pbf, out_path, pixel_size_m=args.pixel_size_m)
        )

    log.info("=" * 60)
    log.info("Summary: %d tile processed", len(summary))
    for s in summary:
        log.info(
            "  %s: %d buildings, %.2f%% covered, %.0fs",
            s["tile"],
            s["buildings"],
            s["pct_cells_covered"],
            s["elapsed_s"],
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
