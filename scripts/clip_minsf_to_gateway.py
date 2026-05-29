"""Clip min-SF geojson to the SF12 polygon containing the gateway.

Post-process `<gw_code>.geojson` của precompute_minsf để loại bỏ "đảo
coverage" rời rạc do DSM artifact / LoS ngẫu nhiên qua thung lũng. Giữ
duy nhất vùng connected (liền) chứa gateway.

Thuật toán:
1. Load FeatureCollection.
2. Trong feature SF12 (band rộng nhất, chứa toàn bộ coverage extent),
   tìm polygon chứa điểm gateway (gw_lon, gw_lat) — gọi là `P_main`.
3. Mỗi feature SF7..SF12: giữ polygon nào có centroid nằm trong `P_main`.
   - Test centroid (KHÔNG phải first vertex) vì khi polygon == P_main,
     first vertex nằm trên biên → ray-casting trả False sai → mất P_main.
4. Xoá feature trống (không còn polygon nào).

Usage:
    uv run python scripts/clip_minsf_to_gateway.py <code>
    uv run python scripts/clip_minsf_to_gateway.py 7276ff002e0507da
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = REPO_ROOT / "apps" / "web-app" / "public" / "coverage" / "minsf"


def _point_in_polygon(x: float, y: float, ring: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon (ring tự-đóng [first==last] hoặc không, OK cả 2)."""
    n = len(ring)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi):
            inside = not inside
        j = i
    return inside


def _centroid(ring: list[list[float]]) -> tuple[float, float]:
    """Centroid (trung bình tọa độ vertex), bỏ vertex cuối nếu trùng đầu."""
    if len(ring) >= 2 and ring[0] == ring[-1]:
        verts = ring[:-1]
    else:
        verts = ring
    n = len(verts)
    cx = sum(p[0] for p in verts) / n
    cy = sum(p[1] for p in verts) / n
    return cx, cy


def clip(path: Path, backup: bool = True) -> dict[str, int]:
    """Clip file in-place, trả về thống kê {sf: polys_kept}."""
    gj = json.loads(path.read_text(encoding="utf-8"))
    gw_lon = gj["properties"]["gateway_lon"]
    gw_lat = gj["properties"]["gateway_lat"]

    sf12 = next((f for f in gj["features"] if f["properties"]["min_sf"] == 12), None)
    if sf12 is None:
        raise RuntimeError("Không có feature SF12 trong file")

    # Tìm SF12 polygon chứa gw
    p_main: list[list[float]] | None = None
    for poly in sf12["geometry"]["coordinates"]:
        outer = poly[0]
        if _point_in_polygon(gw_lon, gw_lat, outer):
            p_main = outer
            break
    if p_main is None:
        # Fallback: polygon có centroid gần gw nhất
        best, best_d = None, float("inf")
        for poly in sf12["geometry"]["coordinates"]:
            cx, cy = _centroid(poly[0])
            d = (cx - gw_lon) ** 2 + (cy - gw_lat) ** 2
            if d < best_d:
                best_d, best = d, poly[0]
        p_main = best
        print("WARNING: gw không trong bất kỳ SF12 polygon — dùng polygon gần nhất")

    assert p_main is not None
    print(f"P_main: {len(p_main)} verts")

    if backup:
        bak = path.with_suffix(path.suffix + ".preclip")
        if not bak.exists():
            shutil.copy(path, bak)
            print(f"Backup → {bak.name}")

    stats: dict[int, int] = {}
    for feat in gj["features"]:
        sf = feat["properties"]["min_sf"]
        kept: list[list[list[list[float]]]] = []
        for poly in feat["geometry"]["coordinates"]:
            cx, cy = _centroid(poly[0])
            if _point_in_polygon(cx, cy, p_main):
                kept.append(poly)
        before = len(feat["geometry"]["coordinates"])
        feat["geometry"]["coordinates"] = kept
        stats[sf] = len(kept)
        print(f"  SF{sf}: {before} → {len(kept)} polys")

    gj["features"] = [f for f in gj["features"] if f["geometry"]["coordinates"]]
    gj["properties"]["clipped_to_gateway"] = True

    path.write_text(json.dumps(gj), encoding="utf-8")
    print(f"Wrote {path} ({path.stat().st_size} bytes)")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", help="Gateway code (vd 7276ff002e0507da)")
    parser.add_argument(
        "--dir",
        default=str(DEFAULT_DIR),
        help=f"Directory chứa <code>.geojson. Default: {DEFAULT_DIR}",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Không tạo .preclip backup",
    )
    args = parser.parse_args()

    path = Path(args.dir) / f"{args.code}.geojson"
    if not path.is_file():
        print(f"Không tìm thấy {path}", file=sys.stderr)
        return 1

    clip(path, backup=not args.no_backup)
    return 0


if __name__ == "__main__":
    sys.exit(main())
