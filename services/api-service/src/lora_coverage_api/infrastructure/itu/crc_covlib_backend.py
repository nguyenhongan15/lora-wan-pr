"""crc-covlib adapter implementing `Stage1PhysicsBackend`.

Lib: crc-covlib 4.6.2 (CRC Canada, MIT). Wraps ITU-R P.1812-**7** (terrain
diffraction) through C++ core — XÁC MINH 2026-06-27: crc-covlib 4.6.2 implement
edition -7 (digital maps P.453/P.1510/P.836 bundled trong wheel). Thư mục
`core-logic/model/R-REC-P.1812-8-*` là tài liệu tham khảo rời, KHÔNG được lib
dùng. P.2108-1 clutter qua Python helper. DEM = Copernicus GLO-30 GeoTIFF tiles
under `dem_directory`. Cấu hình P.1812 + P.2108 → `p1812_config` (dùng chung heatmap).

Clutter strategy:
  - Có DSM (`surface_dem_directory`): P.1812 đã model nhiễu xạ qua building/
    canopy bằng surface elevation thật → bỏ P.2108 statistic (tránh double-
    count; xem verify_p2108_double_count_2026_05_31).
  - Không DSM: dùng P.2108 statistic làm fallback clutter loss.

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

# (DEM sampling resolution + cấu hình P.1812 + P.2108 → infrastructure/itu/p1812_config.py,
#  dùng chung với heatmap để không drift.)


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

        from .p1812_config import configure_p1812_propagation, p2108_clutter_db

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

        # Cấu hình P.1812 + nguồn DEM/Surface DÙNG CHUNG với heatmap (p1812_config)
        # → tránh drift tham số giữa /predict và "bản đồ ước lượng".
        configure_p1812_propagation(
            sim,
            time_pct=self.percent_time,
            loc_pct=self.percent_location,
            dem_dir=str(self.dem_directory),
            surface_dir=(str(self.surface_dem_directory) if self.surface_dem_directory else None),
        )

        pl_p1812 = sim.GenerateReceptionPointResult(link.rx.latitude, link.rx.longitude)

        if not math.isfinite(pl_p1812):
            raise RuntimeError(
                f"P.1812 trả non-finite ({pl_p1812}) cho link "
                f"tx=({link.tx.latitude},{link.tx.longitude}) "
                f"rx=({link.rx.latitude},{link.rx.longitude}); "
                f"khả năng DEM không cover bbox."
            )

        # P.2108 clutter: tự tắt khi có DSM (tránh double-count), gate ≥0.25km —
        # logic dùng chung p1812_config.p2108_clutter_db.
        d_km = _haversine_km(
            link.tx.latitude, link.tx.longitude, link.rx.latitude, link.rx.longitude
        )
        clutter_db = p2108_clutter_db(
            link.freq_mhz,
            d_km,
            self.percent_location,
            has_surface=self.surface_dem_directory is not None,
        )

        return float(pl_p1812 + clutter_db)

    def building_entry_loss_db(self, freq_mhz: float, probability_percent: float) -> float:
        """ITU-R P.2109 BEL — traditional building, elevation 0° (terrestrial).

        Probability = persentile của distribution: 50% ≈ "indoor", 90% ≈ "sâu
        trong nhà". Hard-code traditional vì VN context (gạch + bê tông), không
        phải thermally-efficient (kính low-E + insulation kiểu hiện đại châu Âu);
        nếu sau này expose tower-mounted IoT → cần extend.
        """
        from crc_covlib.helper import itur_p2109  # type: ignore[import-untyped]

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
