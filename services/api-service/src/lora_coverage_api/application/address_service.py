"""AddressResolutionService — F2 geocoding cascade.

Theo business-logic.md §geocoding:
    Postgres canonical (free, fast) → Nominatim (free, rate-limited) →
    VietMap → Goong → Google (last resort, sponsor only — defer)

Service KHÔNG biết về HTTP — chỉ phụ thuộc 2 protocol:
    AddressCache (read/write address.canonical)
    GeocodingClient (HTTP call thực sự, ở infrastructure) — cùng shape cho
    Nominatim / VietMap / Goong.

Cascade rule:
    1. parse_coordinates → trả luôn nếu input là tọa độ (decimal/DMS).
    2. Hit cache → trả luôn (giữ provider gốc của lần promote đầu).
    3. Miss → gọi nominatim. Nếu hit + in_vietnam → cache + trả.
    4. Nominatim NOT_FOUND hoặc Unavailable → thử lần lượt fallbacks
       (VietMap → Goong). First hit + in_vietnam → cache + trả.
    5. Out-of-region: KHÔNG cache (tránh poison cache khi user phân vân toạ độ).
    6. Tất cả tier đều không có data → NOT_FOUND.
       Tất cả tier đều Unavailable → PROVIDER_UNAVAILABLE.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import structlog

from ..domain.address import Address, AddressLookupResult, GeocodingProvider
from ..domain.errors import AddressLookupError, AddressLookupErrorCode
from ..domain.result import Err, Ok, Result
from .coordinate_parser import parse_coordinates
from .repositories import AddressCache

logger = structlog.get_logger("lora_coverage_api.address_service")


class GeocodingClient(Protocol):
    """Generic HTTP geocoder.

    Mọi tier (Nominatim, VietMap, Goong) đều implement shape này.
    Trả None nếu không tìm thấy; raise GeocodingProviderUnavailable nếu
    provider lỗi (rate-limit, timeout, 5xx).
    """

    provider: GeocodingProvider

    def search(self, query: str) -> AddressLookupResult | None:
        ...


# Back-compat alias — tests/fakes/address.py vẫn import name này.
NominatimClient = GeocodingClient


class GeocodingProviderUnavailable(Exception):
    """Provider trả 5xx / timeout / rate-limit. Service map về Err.

    Mọi geocoding client (Nominatim/VietMap/Goong) raise đúng exception này
    để service cascade biết khi nào fallback sang tier kế.
    """


# Back-compat alias.
NominatimUnavailable = GeocodingProviderUnavailable


class AddressResolutionService:
    """Cascade geocoder.

    `nominatim` là tier 2 (default chính, free). `fallbacks` là tier 3+
    (paid VN-first), được thử tuần tự khi tier 2 không trả kết quả hoặc
    không khả dụng.
    """

    def __init__(
        self,
        cache: AddressCache,
        nominatim: GeocodingClient,
        *,
        fallbacks: Sequence[GeocodingClient] = (),
    ) -> None:
        self._cache = cache
        self._nominatim = nominatim
        self._fallbacks = tuple(fallbacks)

    def lookup(
        self, address: Address
    ) -> Result[AddressLookupResult, AddressLookupError]:
        # ── Tier 0: tọa độ trực tiếp (decimal/DMS) ───────────────────────
        # Vì đây là input rõ ràng nhất — không cần đi cascade geocoding.
        # Vẫn áp invariant is_in_vietnam.
        coords = parse_coordinates(address.raw)
        if coords is not None:
            lat, lng = coords
            hit = AddressLookupResult(
                latitude=lat,
                longitude=lng,
                display_name=f"{lat:.5f}, {lng:.5f}",
                provider=GeocodingProvider.POSTGRES,
                confidence=1.0,
            )
            if not hit.is_in_vietnam:
                return Err(
                    AddressLookupError(
                        code=AddressLookupErrorCode.OUT_OF_REGION,
                        message=(
                            f"Toạ độ ngoài lãnh thổ VN: {lat:.4f},{lng:.4f}"
                        ),
                    )
                )
            return Ok(hit)

        key = address.normalized
        if not key:
            return Err(
                AddressLookupError(
                    code=AddressLookupErrorCode.NOT_FOUND,
                    message="Địa chỉ rỗng sau khi chuẩn hoá.",
                )
            )

        # ── Tier 1: cache ────────────────────────────────────────────────
        cached = self._cache.get(key)
        if cached is not None:
            # Cache trả với provider gốc (vd NOMINATIM khi promoted lên cache).
            # Không thay đổi provider — giữ provenance.
            return Ok(cached)

        # ── Tier 2..N cascade ────────────────────────────────────────────
        # Thử lần lượt: nominatim (tier 2) → fallbacks (tier 3+).
        # `all_unavailable` = mọi tier đều raise → trả PROVIDER_UNAVAILABLE thay vì NOT_FOUND.
        tiers: tuple[GeocodingClient, ...] = (self._nominatim, *self._fallbacks)
        all_unavailable = True
        out_of_region_seen: AddressLookupResult | None = None

        for client in tiers:
            try:
                hit = client.search(address.raw)
            except GeocodingProviderUnavailable as e:
                logger.warning(
                    "geocoder.unavailable",
                    provider=getattr(client, "provider", "?"),
                    error=str(e),
                )
                continue
            all_unavailable = False

            if hit is None:
                continue
            if not hit.is_in_vietnam:
                # Ghi nhận để báo cáo lỗi rõ hơn nếu tất cả tier đều OOR.
                # KHÔNG cache miss-positive.
                out_of_region_seen = hit
                continue

            # Promote lên cache (giữ provider gốc của tier hit).
            self._cache.put(key, hit)
            return Ok(hit)

        if all_unavailable:
            return Err(
                AddressLookupError(
                    code=AddressLookupErrorCode.PROVIDER_UNAVAILABLE,
                    message="Tất cả geocoding provider đều không khả dụng.",
                )
            )

        if out_of_region_seen is not None:
            return Err(
                AddressLookupError(
                    code=AddressLookupErrorCode.OUT_OF_REGION,
                    message=(
                        f"Địa chỉ trả ra ngoài lãnh thổ VN: "
                        f"{out_of_region_seen.latitude:.4f},{out_of_region_seen.longitude:.4f}"
                    ),
                )
            )

        return Err(
            AddressLookupError(
                code=AddressLookupErrorCode.NOT_FOUND,
                message=f"Không tìm thấy địa chỉ: {address.raw!r}",
            )
        )
