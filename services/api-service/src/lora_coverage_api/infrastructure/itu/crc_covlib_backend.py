"""crc-covlib adapter implementing `Stage1PhysicsBackend`.

Lib: crc-covlib (CRC Canada, MIT). Wraps ITU-R P.1812-7 (terrain diffraction)
through C++ core, P.2108-1 clutter through Python helper. DEM = Copernicus
GLO-30 GeoTIFF tiles under `dem_directory`.

Design (Ousterhout Ch 4 deep module):
  - Interface: `basic_transmission_loss_db(link) -> float`.
  - Hidden: Simulation object lifecycle, DEM source wiring, percent_time/
    location config, surface-profile method, P.2108 helper invocation, unit
    conversions (MHz→GHz).

Thread-safety:
  - crc-covlib `Simulation` keeps internal state (transmitter location, freq).
  - Strategy: build 1 Simulation per call. Cheap (~4 ms total bao gồm DEM
    sampling — đo trên smoke test). Tránh share Simulation giữa request →
    không cần lock, không cần ThreadLocal.
  - DEM file handles được crc-covlib cache nội bộ (theo source dir), nên build
    Simulation mỗi call KHÔNG đọc lại tile từ disk.

Failure mode:
  - DEM không cover bbox link → crc-covlib trả NaN/giá trị bất thường. Wrap
    với check `math.isfinite` để raise rõ ràng — caller (orchestrator) trả
    HTTP 5xx vì đây là ops bug (DEM mount thiếu), không phải user error.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from ...application.itu.backend import LinkGeometry

# crc-covlib import lazy bên trong `basic_transmission_loss_db` — file phải
# import được trên môi trường chưa cài lib (vd CI test collection chạy unit
# tests không cần backend thật). Fail tại runtime, không tại module load.

# DEM sampling resolution. 30 m khớp Copernicus GLO-30 cell size. Tăng (vd 100m)
# nếu DEM thưa hơn để giảm số sample/link; giảm dưới 30m vô nghĩa vì DEM source
# đã là 30m.
_DEM_SAMPLING_RESOLUTION_M = 30


@dataclass(frozen=True, slots=True)
class CrcCovlibBackend:
    """ITU-R P.1812 + P.2108 backend qua crc-covlib.

    What:
      - `basic_transmission_loss_db(link)` → P.1812 diffraction loss + P.2108
        statistical clutter loss (dB).
    Construction:
      - `dem_directory`: path tới folder chứa GeoTIFF tiles (cả terrain & surface).
        crc-covlib auto-detect tile dựa trên bbox của link.
      - `percent_time` / `percent_location`: ITU-R P.1812 statistical params
        (mặc định 50/50 = median). 95/95 cho worst-case design margin.
      - Dùng `field(default=...)` cho immutable defaults → frozen-safe.

    model_version: chuỗi identifier cho audit/replay. Format `itu-p1812-{covlib_ver}`
        — Stage 2 ML có thể filter theo version khi tái huấn luyện.
    """

    dem_directory: Path
    surface_dem_directory: Path | None = None
    model_version: str = "itu-p1812-p2108-crccovlib"
    percent_time: float = 50.0
    percent_location: float = 50.0

    def __post_init__(self) -> None:
        # Boundary check ngay constructor — fail-fast nếu deploy thiếu DEM, không
        # chờ tới request đầu tiên.
        if not self.dem_directory.is_dir():
            raise ValueError(
                f"dem_directory không tồn tại hoặc không phải directory: {self.dem_directory}"
            )
        if self.surface_dem_directory is not None and not self.surface_dem_directory.is_dir():
            raise ValueError(
                f"surface_dem_directory không tồn tại hoặc không phải directory: {self.surface_dem_directory}"
            )
        if not 0.0 < self.percent_time <= 100.0:
            raise ValueError(f"percent_time ngoài (0, 100]: {self.percent_time}")
        if not 0.0 < self.percent_location <= 100.0:
            raise ValueError(f"percent_location ngoài (0, 100]: {self.percent_location}")

    def basic_transmission_loss_db(self, link: LinkGeometry) -> float:
        from crc_covlib import simulation as covlib  # type: ignore[import-untyped]
        from crc_covlib.helper import itur_p2108  # type: ignore[import-untyped]

        # ITU digital maps (P.453 refractivity DN50/N050, P.1510 T_Annual, P.836
        # water vapor) được crc-covlib wheel ship sẵn trong
        # <site-packages>/crc_covlib/data/itu_proprietary/. C++ core đọc tự động
        # — không cần env var override.

        sim = covlib.Simulation()

        sim.SetTransmitterLocation(link.tx.latitude, link.tx.longitude)
        sim.SetTransmitterHeight(link.tx_antenna_height_m)
        sim.SetTransmitterFrequency(link.freq_mhz)
        # EIRP set tới 0.025 W (~14 dBm) chỉ để Simulation hợp lệ; ResultType
        # PATH_LOSS_DB nghĩa là return = PL không phụ thuộc TX power. Số này
        # chỉ là sentinel — link-budget thật làm ở application layer.
        sim.SetTransmitterPower(0.025, covlib.PowerType.EIRP)
        sim.SetReceiverHeightAboveGround(link.rx_antenna_height_m)

        sim.SetPropagationModel(covlib.PropagationModel.ITU_R_P_1812)
        sim.SetITURP1812TimePercentage(self.percent_time)
        sim.SetITURP1812LocationPercentage(self.percent_location)
        sim.SetITURP1812SurfaceProfileMethod(
            covlib.P1812SurfaceProfileMethod.P1812_USE_SURFACE_ELEV_DATA
        )

        dem_str = str(self.dem_directory)
        sim.SetPrimaryTerrainElevDataSource(covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF)
        sim.SetTerrainElevDataSourceDirectory(
            covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF, dem_str
        )
        # Surface dir riêng (DTM + building heights) khi có DSM; fallback về
        # dem_directory để P.1812 vẫn có data nguồn — clutter sẽ bù qua P.2108.
        surface_str = (
            str(self.surface_dem_directory) if self.surface_dem_directory is not None else dem_str
        )
        sim.SetPrimarySurfaceElevDataSource(covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF)
        sim.SetSurfaceElevDataSourceDirectory(
            covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF, surface_str
        )

        sim.SetResultType(covlib.ResultType.PATH_LOSS_DB)
        sim.SetTerrainElevDataSamplingResolution(_DEM_SAMPLING_RESOLUTION_M)

        pl_p1812 = sim.GenerateReceptionPointResult(link.rx.latitude, link.rx.longitude)

        if not math.isfinite(pl_p1812):
            raise RuntimeError(
                f"P.1812 trả non-finite ({pl_p1812}) cho link "
                f"tx=({link.tx.latitude},{link.tx.longitude}) "
                f"rx=({link.rx.latitude},{link.rx.longitude}); "
                f"khả năng DEM không cover bbox."
            )

        d_km = _haversine_km(
            link.tx.latitude, link.tx.longitude, link.rx.latitude, link.rx.longitude
        )
        # P.2108-1 §3.2 valid cho 0.25 ≤ d ≤ 100 km. Dưới ngưỡng (vd target trùng
        # toạ độ gateway → d=0) → công thức `log10(d)` blow-up. Vật lý: ở cự ly
        # < 250 m clutter loss không đáng kể so với free-space + diffraction
        # P.1812 đã tính, set 0.
        if d_km < 0.25:
            clutter_db = 0.0
        else:
            clutter_db = itur_p2108.TerrestrialPathClutterLoss(
                link.freq_mhz / 1000.0, d_km, self.percent_location
            )

        return float(pl_p1812 + clutter_db)

    def building_entry_loss_db(self, freq_mhz: float, probability_percent: float) -> float:
        """ITU-R P.2109 BEL — traditional building, elevation 0° (terrestrial).

        Probability = persentile của distribution: 50% ≈ "indoor", 90% ≈ "sâu
        trong nhà". Hard-code traditional vì VN context (gạch + bê tông), không
        phải thermally-efficient (kính low-E + insulation kiểu hiện đại châu Âu);
        nếu sau này expose tower-mounted IoT → cần extend.
        """
        from crc_covlib.helper import itur_p2109

        if not 0.0 < probability_percent < 100.0:
            raise ValueError(f"probability_percent ngoài (0, 100): {probability_percent}")
        bel = itur_p2109.BuildingEntryLoss(
            freq_mhz / 1000.0,
            probability_percent,
            itur_p2109.BuildingType.TRADITIONAL,
            0.0,
        )
        if not math.isfinite(bel):
            raise RuntimeError(
                f"P.2109 BEL non-finite ({bel}) cho freq={freq_mhz} MHz, "
                f"prob={probability_percent}%"
            )
        return float(bel)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
