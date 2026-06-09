"""Fetch OSM landuse + natural=water polygons via Overpass, save GeoJSON.

Reference module (`processing/terrain.py:get_terrain_type`) needs polygons with
`landuse` or `natural` tag for forest/water/residential ratio features.

Usage:
    uv run --with osmnx --with geopandas python scripts/fetch_osm_landuse.py --region danang
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import osmnx as ox

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "osm"

BBOXES = {
    "danang": (107.9, 15.8, 108.5, 16.3),
    "haiphong": (106.55, 20.7, 106.85, 21.0),
}

TAGS = {"landuse": True, "natural": ["water"]}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--region", choices=list(BBOXES.keys()), default="danang")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    log = logging.getLogger("fetch_osm")

    west, south, east, north = BBOXES[args.region]
    log.info(
        "Fetching OSM landuse + natural=water for %s bbox=(W=%.3f S=%.3f E=%.3f N=%.3f)",
        args.region,
        west,
        south,
        east,
        north,
    )

    gdf = ox.features_from_bbox(bbox=(west, south, east, north), tags=TAGS)
    log.info("Fetched %d features", len(gdf))

    keep_cols = [c for c in ["landuse", "natural", "geometry"] if c in gdf.columns]
    gdf = gdf[keep_cols].reset_index(drop=True)
    gdf = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])]
    log.info("After polygon filter: %d features", len(gdf))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"landuse_{args.region}.geojson"
    gdf.to_file(out_path, driver="GeoJSON")
    log.info("Saved → %s (%d features)", out_path, len(gdf))


if __name__ == "__main__":
    main()
