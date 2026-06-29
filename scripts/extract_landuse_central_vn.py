"""Extract OSM landuse + natural polygons cho central VN từ PBF.

Output GeoJSON dùng làm asset cho `build_training_csv.py` (compute residential_ratio,
forest_ratio, water_ratio dọc path TX-RX). Tách khỏi reference_wireless để cover
Huế (16.0-16.7N) + Đà Nẵng (15.9-16.2N) + Quảng Nam (15.0-16.0N) — bbox cũ
chỉ Đà Nẵng nội thành.

Run 1 lần (asset persistent):
    docker compose exec celery-worker python /app/scripts/extract_landuse_central_vn.py

Schema: GeoJSON FeatureCollection, mỗi feature có properties:
  - landuse: str (residential, forest, commercial, industrial, farmland, ...)
  - natural: str (water, wood, ...) — fallback khi không có landuse

Time scan: ~2-5 phút (osmium scan toàn PBF VN ~1.5GB).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import osmium
from shapely import wkb as shp_wkb
from shapely.geometry import box, mapping

log = logging.getLogger("extract_landuse")

PBF_PATH = Path(os.environ.get("LORA_OSM_PBF", "/data/osm/vietnam-260512.osm.pbf"))
OUT_PATH = Path(
    os.environ.get(
        "LORA_LANDUSE_OUT",
        "/app/services/ml-service/data/training/terrain/landuse_central.geojson",
    )
)

# bbox central VN: cover Huế + Đà Nẵng + Quảng Nam (+ buffer).
BBOX = (106.5, 14.5, 109.5, 17.5)  # (minx, miny, maxx, maxy) WGS84


class _LanduseHandler(osmium.SimpleHandler):
    """Collect polygons có tag landuse=* hoặc natural=* (fallback) trong bbox."""

    def __init__(self, bbox: tuple[float, float, float, float]):
        super().__init__()
        self.bbox = bbox
        self.box = box(*bbox)
        self.features: list[dict] = []
        self._wkb = osmium.geom.WKBFactory()
        self._skipped = 0

    def area(self, a: osmium.osm.Area) -> None:
        landuse = a.tags.get("landuse", "").strip().lower() or None
        natural = a.tags.get("natural", "").strip().lower() or None
        if not landuse and not natural:
            return

        try:
            env = a.envelope()
            if env is None:
                return
            bl = env.bottom_left
            tr = env.top_right
            if (
                tr.lon < self.bbox[0]
                or bl.lon > self.bbox[2]
                or tr.lat < self.bbox[1]
                or bl.lat > self.bbox[3]
            ):
                return
        except Exception:
            pass

        try:
            wkb = self._wkb.create_multipolygon(a)
        except RuntimeError:
            self._skipped += 1
            return

        geom = shp_wkb.loads(wkb, hex=False)
        if geom.is_empty:
            return
        if not self.box.intersects(geom):
            return

        props = {}
        if landuse:
            props["landuse"] = landuse
        if natural:
            props["natural"] = natural

        self.features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": mapping(geom),
            }
        )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not PBF_PATH.exists():
        log.error("PBF not found: %s", PBF_PATH)
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    log.info("scanning PBF for landuse in bbox %s ...", BBOX)
    t0 = time.time()
    handler = _LanduseHandler(BBOX)
    handler.apply_file(str(PBF_PATH), locations=True)
    log.info(
        "collected %d polygons (%.0fs scan, %d broken skipped)",
        len(handler.features),
        time.time() - t0,
        handler._skipped,
    )

    fc = {
        "type": "FeatureCollection",
        "bbox": list(BBOX),
        "features": handler.features,
    }
    OUT_PATH.write_text(json.dumps(fc))
    size_mb = OUT_PATH.stat().st_size / 1e6
    log.info("wrote %s (%.1f MB)", OUT_PATH, size_mb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
