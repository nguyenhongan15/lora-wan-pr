"""Dependency injection wiring.

Edge là chỗ DUY NHẤT biết tới infrastructure. Application chỉ thấy protocols.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import Engine

from ..application.address_service import (
    AddressResolutionService,
    GeocodingClient,
)
from ..application.coverage_service import CoverageQueryService
from ..application.identity import (
    AdminRequiredError,
    IdentityService,
    InvalidCredentialsError,
    User,
)
from ..application.linking import CredentialCipher, LinkingService
from ..application.path_loss import Stage1LogDistanceModel
from ..application.repositories import (
    AddressResolution,
    CoverageQuery,
    GatewayDirectory,
    SurveyIngest,
)
from ..application.sync import SyncService
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


# ── Identity (plan-auth-v1 §3.1) ──────────────────────────────────────────


@lru_cache(maxsize=1)
def _identity_service() -> IdentityService:
    s = _settings()
    return IdentityService(jwt_secret=s.jwt_secret, jwt_ttl_hours=s.jwt_ttl_hours)


def identity_service() -> IdentityService:
    return _identity_service()


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise InvalidCredentialsError("Thiếu Authorization header")
    parts = authorization.split(maxsplit=1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise InvalidCredentialsError("Authorization header phải dạng 'Bearer <token>'")
    return parts[1].strip()


def current_user(
    identity: Annotated[IdentityService, Depends(identity_service)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """FastAPI dependency: resolve User từ Bearer token, raise nếu sai/hết hạn."""
    token = _extract_bearer(authorization)
    with _engine().begin() as conn:
        return identity.current_user(conn, token)


def current_user_optional(
    identity: Annotated[IdentityService, Depends(identity_service)],
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    """Như `current_user` nhưng trả None khi không kèm Authorization header.

    Dùng cho endpoint public-default (vd /survey/training mode community)
    nhưng vẫn cho phép authenticated user pass token để dùng filter `me`.
    Token sai/hết hạn vẫn raise 401 — nhất quán với `current_user`.
    """
    if not authorization:
        return None
    token = _extract_bearer(authorization)
    with _engine().begin() as conn:
        return identity.current_user(conn, token)


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    """Gate cho /admin/*. Resolve current_user trước rồi assert is_admin.

    Tách khỏi `current_user` để route nào không cần admin vẫn dùng dep gốc,
    còn route admin gắn thêm dep này — FastAPI cache User instance qua scope
    request nên không double-fetch.
    """
    if not user.is_admin:
        raise AdminRequiredError("Endpoint yêu cầu quyền admin")
    return user


# ── Linking (plan-auth-v1 §3.3) ───────────────────────────────────────────


@lru_cache(maxsize=1)
def _credential_cipher() -> CredentialCipher:
    """Shared cipher instance — Linking encrypt/decrypt + Sync decrypt dùng
    chung. Plan §2: cipher là primitive (không phải application module),
    cross-module sharing qua DI hợp lệ.
    """
    return CredentialCipher(keys=_settings().linking_fernet_keys_list)


@lru_cache(maxsize=1)
def _linking_service() -> LinkingService:
    return LinkingService(cipher=_credential_cipher())


def linking_service() -> LinkingService:
    return _linking_service()


@lru_cache(maxsize=1)
def _sync_service() -> SyncService:
    return SyncService(cipher=_credential_cipher())


def sync_service() -> SyncService:
    return _sync_service()
