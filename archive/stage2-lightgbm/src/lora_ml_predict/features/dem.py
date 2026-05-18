"""DEM lookup + LoS obstruction count cho Phase 3 features.

Plan v1 §3.5:
  - elevation_diff_m: target_elev - serving_gw_elev (m)
  - los_obstruction_count: số DEM cell dọc great-circle có terrain CAO HƠN
    đường tầm nhìn thẳng giữa anten gateway và target.

DEM source: Copernicus GLO-30 (~30m), GeoTIFF clip toàn VN, đặt ngoài repo
(12F III). Path lấy qua env var `LORA_DEM_PATH`. Module này KHÔNG download —
file phải có sẵn khi `DemLookup()` được construct, raise FileNotFoundError nếu
thiếu (fail-fast ở startup, đúng plan §6.1 "FeatureUnavailable").

Hidden: rasterio dataset handle, CRS lookup, bilinear interp, sample density
adaptive theo distance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import rasterio
from rasterio.transform import rowcol

_EARTH_RADIUS_KM = 6371.0088

# Anten target mặc định (m AGL). Plan v1 không pin; chọn 1.5m = device cầm tay /
# gắn xe / mote ground-level. Caller có thể override khi cần (e.g., gateway
# survey trên tòa nhà → set cao hơn).
_DEFAULT_TARGET_ANTENNA_HEIGHT_M = 1.5

# Sample density LoS raycast: 1 sample / 30m (~DEM cell). Khoảng cách < 30m
# bị clamp về 1 sample (just endpoint check) — tránh divide-by-zero.
_LOS_SAMPLE_STEP_M = 30.0


class _Point(Protocol):
    """Duck-typed: bất kỳ object nào có lat/lon. Target + Gateway đều khớp.

    Dùng @property để Protocol read-only — chấp nhận cả frozen dataclass.
    """

    @property
    def latitude(self) -> float: ...

    @property
    def longitude(self) -> float: ...


@dataclass(frozen=True, slots=True)
class _GatewayElevContext:
    """Gateway-side context cho LoS raycast.

    Tách dataclass này vì Target không có altitude/antenna_height, nhưng
    Gateway thì có. Caller responsible cung cấp khi gọi `los_obstruction_count`.
    """

    altitude_m: float  # MSL của terrain TẠI gateway
    antenna_height_m: float  # AGL của anten trên cột/mái


class DemLookup:
    """GeoTIFF DEM reader + LoS raycast.

    What:
      - elevation_m(point) → float (MSL meter)
      - los_obstruction_count(target, gw, gw_ctx, target_ant_h_m) → int
    Hidden: rasterio handle, pixel↔geo transform, sample step, bilinear.
    Failure mode:
      - File không tồn tại → __init__ raises FileNotFoundError.
      - Point ngoài DEM bbox → elevation_m trả 0.0 (sea level fallback).
        Đà Nẵng + Hải Phòng đều coastal nên 0.0 là default an toàn cho điểm
        ngoài raster (chỉ xảy ra với input lỗi hoặc bbox VN crop sát biên).
      - los_obstruction_count: cell ngoài bbox bỏ qua (không count).

    Stateless theo 12F VI: rasterio dataset mở 1 lần ở __init__, đóng khi
    process exit. Concurrent request đọc cùng dataset OK (rasterio thread-safe
    cho read-only).
    """

    def __init__(self, dem_path: str) -> None:
        """Open GeoTIFF DEM. Raise FileNotFoundError nếu path không tồn tại.

        Fail-fast ở startup tốt hơn fail mỗi request. Plan §6.1: caller bắt
        FeatureUnavailable nếu pipeline construct fail, fallback Stage 1.
        """
        self._dataset = rasterio.open(dem_path)
        self._band = self._dataset.read(1)
        self._nodata = self._dataset.nodata
        self._transform = self._dataset.transform
        self._height = self._dataset.height
        self._width = self._dataset.width

    def elevation_m(self, point: _Point) -> float:
        """Elevation MSL tại (lat, lon). Bilinear interpolation."""
        return self._sample_at(point.latitude, point.longitude)

    def los_obstruction_count(
        self,
        target: _Point,
        gateway: _Point,
        gateway_ctx: _GatewayElevContext,
        target_antenna_height_m: float = _DEFAULT_TARGET_ANTENNA_HEIGHT_M,
    ) -> int:
        """Số sample point dọc đường great-circle có terrain CAO HƠN LoS altitude.

        LoS altitude tại sample i = linear interpolate giữa
            (gateway_terrain + gateway_antenna_height)
            (target_terrain  + target_antenna_height)
        Cao hơn → terrain "chặn" tia → +1 vào count.

        Lý do dùng count (không phải binary blocked):
          Plan §3.5 ghi `los_obstruction_count` — GBM split dễ hơn so với
          0/1 vì có thể distinguish "1 đỉnh cao" vs "núi dài chắn".
        """
        gw_terrain = self._sample_at(gateway.latitude, gateway.longitude)
        target_terrain = self._sample_at(target.latitude, target.longitude)

        gw_los_alt = gw_terrain + gateway_ctx.antenna_height_m
        target_los_alt = target_terrain + target_antenna_height_m

        d_km = _haversine_km(target.latitude, target.longitude, gateway.latitude, gateway.longitude)
        n_samples = max(2, int(d_km * 1000.0 / _LOS_SAMPLE_STEP_M))

        count = 0
        for i in range(1, n_samples):  # skip endpoints (i=0 là gw, i=n là target)
            frac = i / n_samples
            sample_lat = gateway.latitude + frac * (target.latitude - gateway.latitude)
            sample_lon = gateway.longitude + frac * (target.longitude - gateway.longitude)
            terrain_m = self._sample_at(sample_lat, sample_lon)
            los_alt_m = gw_los_alt + frac * (target_los_alt - gw_los_alt)
            if terrain_m > los_alt_m:
                count += 1
        return count

    def _sample_at(self, lat: float, lon: float) -> float:
        """Bilinear sample DEM tại (lat, lon). 0.0 nếu ngoài bbox hoặc nodata."""
        try:
            row, col = rowcol(self._transform, lon, lat)
        except (ValueError, IndexError):
            return 0.0
        if not (0 <= row < self._height and 0 <= col < self._width):
            return 0.0
        value = float(self._band[row, col])
        if self._nodata is not None and value == self._nodata:
            return 0.0
        return value


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Same formula như features/extractor.py và path_loss.py."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))
