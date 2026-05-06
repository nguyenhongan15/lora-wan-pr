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
    Trả None nếu không tìm thấy; raise GeocodingProviderUnavailableError nếu
    provider lỗi (rate-limit, timeout, 5xx).
    """

    provider: GeocodingProvider

    def search(self, query: str) -> AddressLookupResult | None: ...


# Back-compat alias — tests/fakes/address.py vẫn import name này.
NominatimClient = GeocodingClient


class GeocodingProviderUnavailableError(Exception):
    """Provider trả 5xx / timeout / rate-limit. Service map về Err.

    Mọi geocoding client (Nominatim/VietMap/Goong) raise đúng exception này
    để service cascade biết khi nào fallback sang tier kế.
    """


# Back-compat alias.
NominatimUnavailable = GeocodingProviderUnavailableError


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

    def lookup(self, address: Address) -> Result[AddressLookupResult, AddressLookupError]:
        # ── Direct hit: tọa độ trực tiếp (decimal/DMS) ───────────────────
        # Parse trực tiếp từ input — KHÔNG phải kết quả cascade geocoding.
        # Vẫn áp invariant is_in_vietnam.
        coords = parse_coordinates(address.raw)
        if coords is not None:
            lat, lng = coords
            direct_hit = AddressLookupResult(
                latitude=lat,
                longitude=lng,
                display_name=f"{lat:.5f}, {lng:.5f}",
                provider=GeocodingProvider.POSTGRES,
                confidence=1.0,
            )
            if not direct_hit.is_in_vietnam:
                return Err(
                    AddressLookupError(
                        code=AddressLookupErrorCode.OUT_OF_REGION,
                        message=(f"Toạ độ ngoài lãnh thổ VN: {lat:.4f},{lng:.4f}"),
                    )
                )
            return Ok(direct_hit)

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
            except GeocodingProviderUnavailableError as e:
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
