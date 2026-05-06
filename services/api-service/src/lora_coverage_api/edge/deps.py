"""Dependency injection wiring.

Edge là chỗ DUY NHẤT biết tới infrastructure. Application chỉ thấy protocols.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine

from ..application.address_service import (
    AddressResolutionService,
    GeocodingClient,
)
from ..application.coverage_service import CoverageQueryService
from ..application.path_loss import Stage1LogDistanceModel
from ..application.repositories import (
    AddressResolution,
    CoverageQuery,
    GatewayDirectory,
    SurveyIngest,
)
from ..config import Settings, get_settings
from ..infrastructure.address_cache_pg import PgAddressCache
from ..infrastructure.db import make_engine
from ..infrastructure.gateway_directory_pg import PgGatewayDirectory
from ..infrastructure.goong_client import GoongHttpClient
from ..infrastructure.nominatim_client import NominatimHttpClient
from ..infrastructure.survey_repository_pg import PgSurveyRepository
from ..infrastructure.vietmap_client import VietmapHttpClient


@lru_cache(maxsize=1)
def _settings() -> Settings:
    return get_settings()


def settings_dep() -> Settings:
    """FastAPI dependency wrapper — đời sống = process (qua lru_cache)."""
    return _settings()


@lru_cache(maxsize=1)
def _engine() -> Engine:
    return make_engine(_settings().database_url)


def gateway_directory() -> GatewayDirectory:
    return PgGatewayDirectory(_engine())


def survey_repository() -> SurveyIngest:
    return PgSurveyRepository(_engine())


def coverage_query() -> CoverageQuery:
    settings = _settings()
    return CoverageQueryService(
        directory=gateway_directory(),
        model=Stage1LogDistanceModel(model_version=settings.ml_model_version),
    )


@lru_cache(maxsize=1)
def _nominatim() -> NominatimHttpClient:
    return NominatimHttpClient()


@lru_cache(maxsize=1)
def _geocoding_fallbacks() -> tuple[GeocodingClient, ...]:
    """Build tier 3+ clients dựa trên config keys.

    KHÔNG raise nếu thiếu key — service vẫn chạy với mỗi Nominatim. Thứ tự
    ưu tiên: VietMap trước Goong (VietMap dataset VN có vẻ rộng hơn, theo
    benchmark nội bộ — có thể đảo ngược nếu dữ liệu thay đổi).
    """
    s = _settings()
    out: list[GeocodingClient] = []
    if s.vietmap_api_key:
        out.append(VietmapHttpClient(api_key=s.vietmap_api_key))
    if s.goong_api_key:
        out.append(GoongHttpClient(api_key=s.goong_api_key))
    return tuple(out)


def address_resolution() -> AddressResolution:
    return AddressResolutionService(
        cache=PgAddressCache(_engine()),
        nominatim=_nominatim(),
        fallbacks=_geocoding_fallbacks(),
    )
