"""ESA WorldCover (2021 v200) → ITU-R P.1812 clutter category mapping.

Áp dụng lên crc-covlib Simulation qua `SetLandCoverClassMapping`. Mapping
này KHÔNG cộng path-loss trực tiếp (tránh double-count với DSM building
heights), mà điều biến **location variability σ_L** của P.1812 — vùng dense
urban có σ_L cao hơn → ở percent_location > 50 (conservative) band thu hẹp
rõ rệt, khớp Figure 11/12 paper Petrariu et al.

Khi nào dùng REPR_CLUTTER_HEIGHT thay vì CLUTTER_CATEGORY:
  - Project hiện tại đã có DSM (DTM + OSM building polygons) → giữ
    P1812_USE_SURFACE_ELEV_DATA + mapping CLUTTER_CATEGORY.
  - Nếu deploy domain không có DSM (vd region mới ngoài Việt Nam), switch
    sang ADD_REPR_CLUTTER_HEIGHT + mapping REPR_CLUTTER_HEIGHT.

ESA WorldCover classes (https://esa-worldcover.org/en/data-access):
   10 Tree cover                 → URBAN_TREES_FOREST (canopy)
   20 Shrubland                  → OPEN_RURAL
   30 Grassland                  → OPEN_RURAL
   40 Cropland                   → OPEN_RURAL
   50 Built-up                   → DENSE_URBAN
   60 Bare / sparse vegetation   → OPEN_RURAL
   70 Snow and ice               → OPEN_RURAL
   80 Permanent water bodies     → WATER_SEA
   90 Herbaceous wetland         → WATER_SEA
   95 Mangroves                  → URBAN_TREES_FOREST (tán dày như rừng)
  100 Moss and lichen            → OPEN_RURAL
"""

from __future__ import annotations

from typing import Any, Final

# Giá trị integer khớp `crc_covlib.simulation.P1812ClutterCategory` enum —
# import lazy ở caller để file này không phụ thuộc crc-covlib lúc test.
_P1812_WATER_SEA: Final[int] = 1
_P1812_OPEN_RURAL: Final[int] = 2
_P1812_SUBURBAN: Final[int] = 3
_P1812_URBAN_TREES_FOREST: Final[int] = 4
_P1812_DENSE_URBAN: Final[int] = 5

# WorldCover class → P.1812 category (default-conservative urban interpretation).
ESA_WORLDCOVER_TO_P1812: Final[dict[int, int]] = {
    10: _P1812_URBAN_TREES_FOREST,
    20: _P1812_OPEN_RURAL,
    30: _P1812_OPEN_RURAL,
    40: _P1812_OPEN_RURAL,
    50: _P1812_DENSE_URBAN,
    60: _P1812_OPEN_RURAL,
    70: _P1812_OPEN_RURAL,
    80: _P1812_WATER_SEA,
    90: _P1812_WATER_SEA,
    95: _P1812_URBAN_TREES_FOREST,
    100: _P1812_OPEN_RURAL,
}

# Default cho class không khai báo (vd cell ngoài bbox tile, NoData).
ESA_WORLDCOVER_DEFAULT_P1812: Final[int] = _P1812_OPEN_RURAL


def apply_esa_worldcover_mapping(sim: Any, landcover_directory: str) -> None:
    """Wire ESA WorldCover GeoTIFF vào Simulation với P.1812 mapping.

    Caller phải đã `import crc_covlib.simulation as covlib`; nhận `sim` là
    `covlib.Simulation()` instance. Tách hàm này ra để CrcCovlibBackend +
    precompute_minsf dùng chung 1 wiring, tránh drift.

    Args:
        sim: crc_covlib.simulation.Simulation instance.
        landcover_directory: path string tới folder chứa ESA WorldCover
            GeoTIFF tiles (vd `E:/DATN/lora-data/landcover/esa-worldcover`).
    """
    from crc_covlib import simulation as covlib  # type: ignore[import-untyped]

    sim.SetPrimaryLandCoverDataSource(covlib.LandCoverDataSource.LAND_COVER_ESA_WORLDCOVER)
    # useIndexFile=False: scan dir mỗi sim init. Số ESA tile cho VN ~5-10
    # file → overhead bỏ qua được. Bật indexing khi nào scale ra ASEAN.
    sim.SetLandCoverDataSourceDirectory(
        covlib.LandCoverDataSource.LAND_COVER_ESA_WORLDCOVER,
        landcover_directory,
        False,  # useIndexFile
        False,  # overwriteIndexFile
    )
    # CLUTTER_CATEGORY = modulate σ_L theo class (giữ DSM intact).
    # REPR_CLUTTER_HEIGHT = thêm height ngay tại receiver (xung đột DSM).
    sim.SetITURP1812LandCoverMappingType(
        covlib.P1812LandCoverMappingType.P1812_MAP_TO_CLUTTER_CATEGORY
    )
    for src_class, p1812_cat in ESA_WORLDCOVER_TO_P1812.items():
        sim.SetLandCoverClassMapping(
            covlib.LandCoverDataSource.LAND_COVER_ESA_WORLDCOVER,
            src_class,
            covlib.PropagationModel.ITU_R_P_1812,
            p1812_cat,
        )
    sim.SetDefaultLandCoverClassMapping(
        covlib.LandCoverDataSource.LAND_COVER_ESA_WORLDCOVER,
        covlib.PropagationModel.ITU_R_P_1812,
        ESA_WORLDCOVER_DEFAULT_P1812,
    )
