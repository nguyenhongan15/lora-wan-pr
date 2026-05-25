"""Dependency injection wiring.

Edge là chỗ DUY NHẤT biết tới infrastructure. Application chỉ thấy protocols.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

import httpx
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
    Mailer,
    User,
)
from ..application.itu.model import Stage1ItuModel
from ..application.linking import CredentialCipher, LinkingService
from ..application.path_loss import resolve_environment_profile
from ..application.prediction_service import PredictionOrchestrator
from ..application.repositories import (
    AddressResolution,
    CoverageQuery,
    DeviceQuery,
    GatewayDirectory,
    SurveyIngest,
)
from ..application.sync import SyncService
from ..application.trust import TrustValidator
from ..application.webhook_auth import WebhookAuthService
from ..config import Settings, get_settings
from ..infrastructure.address_cache_pg import PgAddressCache
from ..infrastructure.db import make_engine
from ..infrastructure.device_repository_pg import PgDeviceRepository
from ..infrastructure.gateway_directory_pg import PgGatewayDirectory
from ..infrastructure.goong_client import GoongHttpClient
from ..infrastructure.itu.crc_covlib_backend import CrcCovlibBackend
from ..infrastructure.nominatim_client import NominatimHttpClient
from ..infrastructure.smtp_mailer import NoOpMailer, SmtpMailer
from ..infrastructure.stage2_client import Stage2Client
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


def device_query() -> DeviceQuery:
    return PgDeviceRepository(_engine())


@lru_cache(maxsize=1)
def _itu_backend() -> CrcCovlibBackend:
    """Singleton backend — Simulation rebuild mỗi call (Ousterhout: hide
    lifecycle), nhưng DEM directory + tham số config thì process-level.
    """
    s = _settings()
    return CrcCovlibBackend(
        dem_directory=Path(s.lora_dem_directory),
        surface_dem_directory=(
            Path(s.lora_surface_dem_directory) if s.lora_surface_dem_directory else None
        ),
        model_version=s.ml_model_version,
        percent_time=s.lora_itu_percent_time,
        percent_location=s.lora_itu_percent_location,
    )


def coverage_query() -> CoverageQuery:
    settings = _settings()
    return CoverageQueryService(
        directory=gateway_directory(),
        model=Stage1ItuModel(
            model_version=settings.ml_model_version,
            backend=_itu_backend(),
            env_profile=resolve_environment_profile(settings.lora_env_profile),
        ),
    )


@lru_cache(maxsize=1)
def _stage2_http_client() -> httpx.AsyncClient | None:
    """Shared AsyncClient cho Stage 2. None khi stage2 disabled (base_url rỗng).

    Lifespan = process; FastAPI shutdown sẽ giữ tham chiếu — chấp nhận leak
    nhỏ vì client là singleton, không có connection rotation logic.
    """
    s = _settings()
    if not s.stage2_predict_base_url:
        return None
    return httpx.AsyncClient(timeout=s.stage2_timeout_seconds)


@lru_cache(maxsize=1)
def _stage2_client() -> Stage2Client | None:
    s = _settings()
    if not s.stage2_predict_base_url:
        return None
    http_client = _stage2_http_client()
    if http_client is None:
        return None
    return Stage2Client(
        base_url=s.stage2_predict_base_url,
        bearer_token=s.stage2_auth_token,
        client=http_client,
    )


def prediction_orchestrator() -> PredictionOrchestrator:
    """Wired: Stage 1 CoverageQueryService + optional Stage 2 client.

    Stage 2 disabled (base_url empty) → orchestrator dùng Stage 1 only.
    """
    return PredictionOrchestrator(
        query=coverage_query(),
        directory=gateway_directory(),
        stage2=_stage2_client(),
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
def _mailer() -> Mailer:
    """SmtpMailer khi `smtp_host` set; NoOpMailer khi rỗng (dev)."""
    s = _settings()
    if not s.smtp_host:
        return NoOpMailer()
    return SmtpMailer(
        host=s.smtp_host,
        port=s.smtp_port,
        username=s.smtp_username or None,
        password=s.smtp_password or None,
        from_email=s.smtp_from_email,
        from_name=s.smtp_from_name,
        use_starttls=s.smtp_use_starttls,
    )


@lru_cache(maxsize=1)
def _identity_service() -> IdentityService:
    s = _settings()
    return IdentityService(
        engine=_engine(),
        jwt_secret=s.jwt_secret,
        access_ttl_minutes=s.access_ttl_minutes,
        refresh_ttl_days=s.refresh_ttl_days,
        lockout_max_attempts=s.login_lockout_max_attempts,
        lockout_window_minutes=s.login_lockout_window_minutes,
        mailer=_mailer(),
        password_reset_ttl_minutes=s.password_reset_ttl_minutes,
        password_reset_url_template=s.password_reset_url_template,
        email_verification_ttl_minutes=s.email_verification_ttl_minutes,
        email_verification_url_template=s.email_verification_url_template,
    )


def mailer_dep() -> Mailer:
    """FastAPI dep cho admin router để gửi thanks email khi approve."""
    return _mailer()


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


# ── Trust validator (plan community-data-contribution §3.4) ───────────────


@lru_cache(maxsize=1)
def _trust_validator() -> TrustValidator:
    """Shared TrustValidator — LinkingService.set_contribution, SyncService
    post-batch promote, ChirpStack webhook ingest post-write, CSV upload
    endpoint đều dùng cùng instance (single Stage1ItuModel + GatewayDirectory).
    """
    settings = _settings()
    return TrustValidator(
        model=Stage1ItuModel(
            model_version=settings.ml_model_version,
            backend=_itu_backend(),
            env_profile=resolve_environment_profile(settings.lora_env_profile),
        ),
        directory=gateway_directory(),
    )


def trust_validator() -> TrustValidator:
    return _trust_validator()


@lru_cache(maxsize=1)
def _linking_service() -> LinkingService:
    return LinkingService(cipher=_credential_cipher(), trust=_trust_validator())


def linking_service() -> LinkingService:
    return _linking_service()


@lru_cache(maxsize=1)
def _sync_service() -> SyncService:
    return SyncService(cipher=_credential_cipher(), trust=_trust_validator())


def sync_service() -> SyncService:
    return _sync_service()


# ── ChirpStack per-user webhook auth ──────────────────────────────────────


@lru_cache(maxsize=1)
def _webhook_auth_service() -> WebhookAuthService:
    """Shared instance — cùng CredentialCipher với LinkingService (1 HMAC
    secret-domain cho cả credential fingerprint lẫn webhook token hash).
    """
    return WebhookAuthService(cipher=_credential_cipher())


def webhook_auth_service() -> WebhookAuthService:
    return _webhook_auth_service()
