"""
services/overpass_client.py — Fetch admin boundary + infrastructure + sub-admin từ OSM Overpass.

Phase v3.1:
  - step 2: AOI admin boundary (fetch_admin_polygon)
  - step 4: Infrastructure points (fetch_infrastructure)
  - step 5: Sub-admin polygons cho urban union (fetch_sub_admin_polygons)

Tuân thủ:
  - SOLID SRP: client tách riêng, không biết DB. *_repo.py lo persistence.
  - SOLID DRY: _post_query() helper chung cho mọi Overpass query.
  - 12-Factor F11: structured logging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import polygonize

logger = logging.getLogger(__name__)

OVERPASS_URL      = "https://overpass-api.de/api/interpreter"
DEFAULT_TIMEOUT_S = 90.0
USER_AGENT        = "lora-coverage/1.0 (AOI bootstrap; admin task)"

# Overpass area ID = relation_id + 3,600,000,000 (way ID + 2,400,000,000)
_AREA_ID_OFFSET = 3_600_000_000


class OverpassError(Exception):
    """Overpass API error (network, timeout, parse, empty result, broken rings)."""


# ─────────────────────────────────────────────────────────────────────────────
# Internal HTTP helper
# ─────────────────────────────────────────────────────────────────────────────

async def _post_query(query: str, timeout_s: float) -> dict:
    """POST query → Overpass, parse JSON. Raise OverpassError on failure."""
    try:
        async with httpx.AsyncClient(
            timeout=timeout_s,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        ) as client:
            resp = await client.post(OVERPASS_URL, data={"data": query})
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        raise OverpassError(f"Overpass HTTP error: {e}") from e
    except ValueError as e:
        raise OverpassError(f"Overpass JSON parse error: {e}") from e


# ─────────────────────────────────────────────────────────────────────────────
# Admin polygon (Phase v3.1 step 2)
# ─────────────────────────────────────────────────────────────────────────────

def _build_query(
    name: str,
    admin_level: int,
    osm_relation_id: int | None,
    timeout_s: int,
) -> str:
    """Build Overpass QL query — relation ID nếu có, fallback name+admin_level."""
    if osm_relation_id is not None:
        selector = f"relation({osm_relation_id})"
    else:
        selector = (
            f'relation["boundary"="administrative"]'
            f'["admin_level"="{admin_level}"]'
            f'["name"="{name}"]'
        )
    return f"[out:json][timeout:{timeout_s}];\n{selector};\nout geom;"


async def fetch_admin_polygon(
    name: str,
    admin_level: int,
    *,
    osm_relation_id: int | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> tuple[MultiPolygon, dict[str, Any]]:
    """Fetch + assemble admin boundary từ OSM Overpass."""
    query = _build_query(name, admin_level, osm_relation_id, int(timeout_s))
    logger.info(
        "overpass.fetch_admin",
        extra={"osmName": name, "adminLevel": admin_level,
               "osmRelationId": osm_relation_id},
    )

    data = await _post_query(query, timeout_s)

    relations = [el for el in data.get("elements", []) if el.get("type") == "relation"]
    if not relations:
        raise OverpassError(
            f"Không tìm thấy relation: name={name!r} admin_level={admin_level} "
            f"osm_relation_id={osm_relation_id}"
        )
    if len(relations) > 1:
        logger.warning(
            "overpass.multiple_matches",
            extra={"osmName": name, "count": len(relations)},
        )

    relation = relations[0]
    multipolygon = _assemble_multipolygon(relation.get("members", []))
    metadata = {
        "osmRelationId": relation["id"],
        "tags":          relation.get("tags", {}),
    }
    return multipolygon, metadata


def _assemble_multipolygon(members: list[dict]) -> MultiPolygon:
    """
    Ghép outer/inner ways của OSM relation thành MultiPolygon.

    Algorithm:
      1. Tách members theo role outer/inner; convert geometry → LineString
      2. shapely.polygonize: stitch rings → Polygons
      3. Mỗi outer polygon: tìm inner polygon nằm trong → thêm làm hole
      4. Combine all → MultiPolygon
    """
    outer_lines: list[LineString] = []
    inner_lines: list[LineString] = []

    for member in members:
        if member.get("type") != "way":
            continue
        coords = [(p["lon"], p["lat"]) for p in member.get("geometry", [])]
        if len(coords) < 2:
            continue
        line = LineString(coords)
        if member.get("role") == "inner":
            inner_lines.append(line)
        else:
            outer_lines.append(line)

    outer_polys = list(polygonize(outer_lines))
    inner_polys = list(polygonize(inner_lines))

    if not outer_polys:
        raise OverpassError(
            "Không assemble được outer polygon nào — relation có ring bị đứt"
        )

    final: list[Polygon] = []
    for outer in outer_polys:
        holes = [
            list(inner.exterior.coords)
            for inner in inner_polys
            if outer.contains(inner)
        ]
        final.append(Polygon(outer.exterior.coords, holes=holes))

    return MultiPolygon(final)


# ─────────────────────────────────────────────────────────────────────────────
# Infrastructure points (Phase v3.1 step 4)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InfraPoint:
    """1 điểm hạ tầng OSM có thể đặt gateway (tower, mast, mái nhà cao)."""
    osm_type:   str
    osm_id:     int
    lat:        float
    lng:        float
    infra_type: str             # "comm_tower" | "comm_mast" | "tall_building"
    tags:       dict[str, Any]


def _build_infra_query(
    bbox: tuple[float, float, float, float],
    timeout_s: int,
) -> str:
    """
    Overpass QL query: comm towers/masts + buildings có `levels` hoặc `height`.
    """
    min_lat, min_lng, max_lat, max_lng = bbox
    bbox_str = f"{min_lat},{min_lng},{max_lat},{max_lng}"
    return f"""[out:json][timeout:{timeout_s}];
(
  node["man_made"="tower"]["tower:type"="communication"]({bbox_str});
  way ["man_made"="tower"]["tower:type"="communication"]({bbox_str});
  node["man_made"="mast"]["tower:type"="communication"]({bbox_str});
  way ["man_made"="mast"]["tower:type"="communication"]({bbox_str});
  way ["building"]["building:levels"]({bbox_str});
  way ["building"]["height"]({bbox_str});
);
out center tags;"""


def _classify_infra(
    tags: dict,
    min_building_levels: int,
    min_building_height_m: float,
) -> str | None:
    man_made   = tags.get("man_made")
    tower_type = tags.get("tower:type")

    if man_made == "tower" and tower_type == "communication":
        return "comm_tower"
    if man_made == "mast" and tower_type == "communication":
        return "comm_mast"

    if tags.get("building"):
        levels_raw = tags.get("building:levels")
        if levels_raw:
            try:
                if int(levels_raw) >= min_building_levels:
                    return "tall_building"
            except (ValueError, TypeError):
                pass

        height_raw = tags.get("height")
        if height_raw:
            try:
                h = float(str(height_raw).replace("m", "").strip())
                if h >= min_building_height_m:
                    return "tall_building"
            except (ValueError, TypeError):
                pass

    return None


def _extract_coords(element: dict) -> tuple[float, float] | None:
    if element["type"] == "node":
        return element["lat"], element["lon"]
    if element["type"] == "way" and "center" in element:
        return element["center"]["lat"], element["center"]["lon"]
    return None


async def fetch_infrastructure(
    bbox: tuple[float, float, float, float],
    *,
    min_building_levels:   int   = 6,
    min_building_height_m: float = 18.0,
    timeout_s:             float = DEFAULT_TIMEOUT_S,
) -> list[InfraPoint]:
    """Fetch comm towers/masts + tall buildings từ OSM Overpass theo bbox."""
    query = _build_infra_query(bbox, int(timeout_s))
    logger.info(
        "overpass.fetch_infra",
        extra={
            "minLat": bbox[0], "minLng": bbox[1],
            "maxLat": bbox[2], "maxLng": bbox[3],
        },
    )

    data = await _post_query(query, timeout_s)

    results: list[InfraPoint] = []
    for el in data.get("elements", []):
        infra_type = _classify_infra(
            el.get("tags", {}),
            min_building_levels,
            min_building_height_m,
        )
        if infra_type is None:
            continue

        coords = _extract_coords(el)
        if coords is None:
            continue
        lat, lng = coords

        results.append(InfraPoint(
            osm_type   = el["type"],
            osm_id     = el["id"],
            lat        = lat,
            lng        = lng,
            infra_type = infra_type,
            tags       = el.get("tags", {}),
        ))

    logger.info(
        "overpass.infra_classified",
        extra={
            "totalElements":   len(data.get("elements", [])),
            "classifiedKept":  len(results),
        },
    )
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Sub-admin polygons (Phase v3.1 step 5 — urban union)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SubAdminPolygon:
    """1 admin polygon con (vd phường, xã) bên trong AOI cha."""
    name:              str
    osm_relation_id:   int
    polygon:           MultiPolygon
    tags:              dict[str, Any]


def _build_sub_admin_query(
    parent_relation_id: int,
    admin_level: int,
    timeout_s: int,
) -> str:
    """
    Lấy tất cả admin relations ở level N nằm BÊN TRONG parent area.
    
    Overpass area syntax: relation_id + 3_600_000_000.
    """
    area_id = parent_relation_id + _AREA_ID_OFFSET
    return f"""[out:json][timeout:{timeout_s}];
area({area_id})->.parent;
relation["admin_level"="{admin_level}"]["boundary"="administrative"](area.parent);
out geom;"""


def _name_matches_prefix(tags: dict, prefix: str) -> bool:
    """Check name HOẶC name:vi có prefix. Empty prefix → match all."""
    if not prefix:
        return True
    return (
        tags.get("name", "").startswith(prefix)
        or tags.get("name:vi", "").startswith(prefix)
    )


async def fetch_sub_admin_polygons(
    parent_relation_id: int,
    admin_level: int,
    *,
    name_prefix: str = "",
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> list[SubAdminPolygon]:
    """
    Fetch tất cả admin polygons ở level N bên trong parent relation.

    Args:
        parent_relation_id: OSM relation ID của AOI cha (vd 1891418 cho Đà Nẵng).
        admin_level: target admin_level (vd 8 cho cấp xã).
        name_prefix: filter theo name prefix (vd "Phường " để chỉ lấy phường);
                     empty string = không filter.

    Returns:
        list[SubAdminPolygon] — đã skip những relation có ring bị đứt.
    """
    query = _build_sub_admin_query(parent_relation_id, admin_level, int(timeout_s))
    logger.info(
        "overpass.fetch_sub_admin",
        extra={
            "parentRelationId": parent_relation_id,
            "adminLevel":       admin_level,
            "namePrefix":       name_prefix,
        },
    )

    data = await _post_query(query, timeout_s)
    relations = [el for el in data.get("elements", []) if el.get("type") == "relation"]

    results: list[SubAdminPolygon] = []
    skipped_broken = 0
    for rel in relations:
        tags = rel.get("tags", {})
        if not _name_matches_prefix(tags, name_prefix):
            continue

        try:
            polygon = _assemble_multipolygon(rel.get("members", []))
        except OverpassError as e:
            logger.warning(
                "overpass.skip_broken_polygon",
                extra={"osmRelationId": rel["id"],
                       "osmName": tags.get("name", ""),
                       "error": str(e)},
            )
            skipped_broken += 1
            continue

        results.append(SubAdminPolygon(
            name            = tags.get("name", ""),
            osm_relation_id = rel["id"],
            polygon         = polygon,
            tags            = tags,
        ))

    logger.info(
        "overpass.sub_admin_filtered",
        extra={
            "totalRelations":    len(relations),
            "matchedPrefix":     len(results) + skipped_broken,
            "skippedBroken":     skipped_broken,
            "kept":              len(results),
        },
    )
    return results