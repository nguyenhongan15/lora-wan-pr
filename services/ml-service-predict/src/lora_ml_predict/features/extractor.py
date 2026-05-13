"""Tabular feature extractor cho Stage 2 (Predict-ML, LightGBM residual).

Plan v1 §3.5 — Phase 3+ scope: Phase 2 features + DEM + OSM + device/gateway
pass-through. 11 cột total.

  Phase 2 (haversine-based):
    - log10_distance_to_serving_gw_km
    - bearing_sin, bearing_cos
    - distance_to_2nd_nearest_gw_km

  Phase 3 (DEM + OSM):
    - elevation_diff_m  = target_terrain - serving_gw_terrain (m)
    - los_obstruction_count  = số DEM cell che line-of-sight
    - urbanization_index  = building footprint fraction trong radius 200m

  Phase 3+ (pass-through device + gateway params):
    - spreading_factor  = SF (7-12), known tại predict-time
    - frequency_mhz     = sub-band AS923-2 VN, known tại predict-time
    - gw_antenna_height_m  = height AGL (Stage 1 dùng linear; GBM bắt non-linear)
    - gw_antenna_gain_dbi  = gateway antenna gain (tương tự)

KHÔNG include snr_db (leak — chỉ có khi đo, không có ở predict-time).
KHÔNG include hour/weekday (API không có timestamp input).

Pure-math + raster lookup — không I/O network. DEM + OSM file mở 1 lần ở
construct, query O(1) mỗi call (12F VI stateless).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .dem import DemLookup, _GatewayElevContext
from .osm import UrbanizationLookup

_EARTH_RADIUS_KM = 6371.0088

# Floor 1 m để tránh log10(0) khi target ≡ serving gateway. 1 m << 100 m (d0
# trong path-loss model) nên không méo feature.
_MIN_DISTANCE_KM = 1e-3


class _Candidate(Protocol):
    """Candidate gateway — chỉ cần lat/lon cho distance_to_2nd_nearest scan."""

    @property
    def latitude(self) -> float: ...

    @property
    def longitude(self) -> float: ...


class _Target(Protocol):
    """Target có thêm device params (sf + freq) làm feature pass-through."""

    @property
    def latitude(self) -> float: ...

    @property
    def longitude(self) -> float: ...

    @property
    def spreading_factor(self) -> int: ...

    @property
    def frequency_mhz(self) -> float: ...


class _ServingGateway(Protocol):
    """Serving gateway cần altitude + antenna height/gain cho LoS + features.

    `id` truyền vào categorical feature (LightGBM native categorical handle).
    String type vì UUID — không có ý nghĩa số học.
    """

    @property
    def id(self) -> object: ...  # UUID-like, str() được

    @property
    def latitude(self) -> float: ...

    @property
    def longitude(self) -> float: ...

    @property
    def altitude_m(self) -> float: ...

    @property
    def antenna_height_m(self) -> float: ...

    @property
    def antenna_gain_dbi(self) -> float: ...


@dataclass(frozen=True, slots=True)
class FeatureVector:
    """Phase 3+ feature vector — tabular, 12 cột (11 numeric + 1 categorical).

    What: 12 feature cho LightGBM Stage 2. 11 numeric + serving_gateway_id (str).
    Hidden: haversine, atan2 bearing, nearest-neighbor scan, DEM bilinear,
        LoS raycast, urbanization raster lookup. SF/freq/antenna là pass-through;
        serving_gateway_id là pass-through string cho LightGBM native categorical.
    Failure mode: KHÔNG có. Default cho mọi edge:
      - < 2 candidate gw → distance_to_2nd = +∞
      - target ≡ serving → log10 clamp về -3 (1 m floor)
      - Điểm ngoài DEM/OSM bbox → 0.0 (sea level / rural)
    Đơn vị:
      - log10_distance_to_serving_gw_km: log10(km), [-3, +2] thực tế
      - bearing_sin/cos: [-1, 1] continuous tại 0°/360°
      - distance_to_2nd_nearest_gw_km: km, ≥ 0
      - elevation_diff_m: m, có thể âm (target thấp hơn gw) hoặc dương
      - los_obstruction_count: int ≥ 0, count cell terrain che LoS
      - urbanization_index: [0, 1], building footprint area fraction
      - spreading_factor: int 7..12 (AS923-2)
      - frequency_mhz: float (~920-925)
      - gw_antenna_height_m: m AGL
      - gw_antenna_gain_dbi: dBi
      - serving_gateway_id: str (UUID) — categorical, LightGBM auto-encode
    """

    log10_distance_to_serving_gw_km: float
    bearing_sin: float
    bearing_cos: float
    distance_to_2nd_nearest_gw_km: float
    elevation_diff_m: float
    los_obstruction_count: int
    urbanization_index: float
    spreading_factor: int
    frequency_mhz: float
    gw_antenna_height_m: float
    gw_antenna_gain_dbi: float
    serving_gateway_id: str


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Khoảng cách great-circle (km). Giống công thức ở path_loss._haversine_km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _initial_bearing_rad(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing từ point 1 → point 2 (rad, [-π, π]).

    Encode bằng (sin, cos) thay vì raw rad/độ để tránh discontinuity 359°→0°
    (GBM split không hiểu wrap-around).
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.atan2(y, x)


class FeaturePipeline:
    """Sinh FeatureVector cho 1 cặp (target, serving_gateway).

    What: extract(target, serving_gw) → FeatureVector 11 cột.
    Hidden: candidate gateway list, haversine math, bearing decomposition,
        nearest-neighbor scan, DEM bilinear, LoS raycast, urbanization raster.
    Failure mode:
      - DEM/OSM file thiếu khi construct → DemLookup/UrbanizationLookup raise
        FileNotFoundError. Caller (plan §6.1) bắt và fallback Stage 1.
      - Per-call: KHÔNG raise. Mọi edge fallback về default (xem FeatureVector).

    Stateless theo 12F VI: load candidate list + raster handle 1 lần khi service
    start; rebuild pipeline khi gateway list / raster file đổi (Phase 5 hot-reload).

    Composition: gọi `DemLookup` + `UrbanizationLookup` qua dependency injection
    để test/swap dễ. Trong production, FeaturePipeline owner construct cả 2
    rồi truyền vào.
    """

    def __init__(
        self,
        candidate_gateways: Sequence[_Candidate],
        dem_lookup: DemLookup,
        urbanization_lookup: UrbanizationLookup,
    ) -> None:
        """Snapshot candidate gateway list + 2 raster handle.

        Immutable sau construct: concurrent request không lo race.
        """
        self._candidates: tuple[_Candidate, ...] = tuple(candidate_gateways)
        self._dem = dem_lookup
        self._urbanization = urbanization_lookup

    def extract(self, target: _Target, serving_gateway: _ServingGateway) -> FeatureVector:
        d_serving_km = _haversine_km(
            target.latitude,
            target.longitude,
            serving_gateway.latitude,
            serving_gateway.longitude,
        )
        log10_d = math.log10(max(d_serving_km, _MIN_DISTANCE_KM))

        bearing = _initial_bearing_rad(
            target.latitude,
            target.longitude,
            serving_gateway.latitude,
            serving_gateway.longitude,
        )

        d_2nd_km = self._distance_to_2nd_nearest(target)

        target_elev = self._dem.elevation_m(target)
        gw_elev = self._dem.elevation_m(serving_gateway)
        elevation_diff_m = target_elev - gw_elev

        los_count = self._dem.los_obstruction_count(
            target=target,
            gateway=serving_gateway,
            gateway_ctx=_GatewayElevContext(
                altitude_m=serving_gateway.altitude_m,
                antenna_height_m=serving_gateway.antenna_height_m,
            ),
        )

        urb = self._urbanization.index_at(target)

        return FeatureVector(
            log10_distance_to_serving_gw_km=log10_d,
            bearing_sin=math.sin(bearing),
            bearing_cos=math.cos(bearing),
            distance_to_2nd_nearest_gw_km=d_2nd_km,
            elevation_diff_m=elevation_diff_m,
            los_obstruction_count=los_count,
            urbanization_index=urb,
            spreading_factor=int(target.spreading_factor),
            frequency_mhz=float(target.frequency_mhz),
            gw_antenna_height_m=float(serving_gateway.antenna_height_m),
            gw_antenna_gain_dbi=float(serving_gateway.antenna_gain_dbi),
            serving_gateway_id=str(serving_gateway.id),
        )

    def _distance_to_2nd_nearest(self, target: _Candidate) -> float:
        """Sort tất cả candidate theo distance, lấy index 1.

        Định nghĩa "2nd nearest": gateway gần thứ 2 trong toàn bộ candidate set
        (không loại trừ serving). Lý do: thường serving CHÍNH là nearest →
        index 1 = nearest alternative, đúng nghĩa "có gateway thay thế gần
        không?".

        Phase 2: linear scan O(n). VN < 100 gateway → < 100 µs/call.
        """
        if len(self._candidates) < 2:
            return float("inf")
        distances = sorted(
            _haversine_km(target.latitude, target.longitude, gw.latitude, gw.longitude)
            for gw in self._candidates
        )
        return distances[1]
