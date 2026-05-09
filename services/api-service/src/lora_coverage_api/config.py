"""Application config — 12-Factor F3 (env-only).

KHÔNG hardcode default cho secrets. Default chỉ cho dev convenience.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    database_url: str = Field(
        default="postgresql+psycopg://lora:lora_test_pw@localhost:5432/lora_coverage",
        description="SQLAlchemy URL. Theo .env.template.",
    )

    cors_allowed_origins: str = Field(
        default="http://localhost:5173",
        description="Comma-separated; strict whitelist (xem rule-design-cors.md).",
    )

    # ── Identity (plan-auth-v1 §3.1) ──────────────────────────────────────
    # Required: app fail-fast nếu thiếu, không có dev fallback. Ai cũng có
    # thể gen `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
    jwt_secret: str = Field(
        ...,
        min_length=32,
        description="HS256 signing key cho access token. Bắt buộc — không default.",
    )
    jwt_ttl_hours: int = Field(
        default=24,
        ge=1,
        le=720,
        description="Access token TTL (giờ). v1 không có refresh nên TTL dài hơn.",
    )

    # ── Linking (plan-auth-v1 §3.3) ───────────────────────────────────────
    # Comma-separated Fernet keys cho MultiFernet rotation. Key đầu = encrypt
    # key hiện tại; tất cả keys = decrypt fallback. Generate:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    linking_fernet_keys: str = Field(
        ...,
        min_length=44,
        description=(
            "Fernet key(s) cho mã hoá credentials linked_sources. Format: "
            "single key, hoặc 'newkey,oldkey1,oldkey2' khi rotate."
        ),
    )

    @property
    def linking_fernet_keys_list(self) -> list[bytes]:
        return [k.strip().encode("ascii") for k in self.linking_fernet_keys.split(",") if k.strip()]

    ml_model_version: str = Field(default="stage1-loglike-v0.1.0")

    # ── Stage 1 path-loss profile (12F III) ──────────────────────────────
    # One of: urban | suburban | rural. Allowlist enforce ở boundary
    # `resolve_environment_profile()` (application/path_loss.py).
    lora_env_profile: str = Field(
        default="suburban",
        description="Path loss environment profile: urban|suburban|rural.",
    )

    rate_limit_default: str = Field(default="60/minute")
    rate_limit_anon: str = Field(default="10/minute")

    chirpstack_webhook_tokens: str = Field(
        default="",
        description=(
            "Comma-separated 'token:uploader_uuid' pairs cho ChirpStack webhook auth. "
            "Vd: 'abc123:11111111-1111-1111-1111-111111111111,def456:2222...'"
        ),
    )

    # ── Geocoding cascade tier 3+ (paid, VN-first) ────────────────────────
    # Để rỗng → service skip tier đó. Có key → wire vào cascade fallback
    # sau Nominatim (xem application/address_service.py + edge/deps.py).
    vietmap_api_key: str = Field(
        default="",
        description="VietMap geocoding API key. Empty = disabled.",
    )
    goong_api_key: str = Field(
        default="",
        description="Goong geocoding API key. Empty = disabled.",
    )

    # ── F2 SLO ────────────────────────────────────────────────────────────
    # P95 lookup end-to-end latency (geocode + predict + render). Theo
    # business-logic.md §8.2 — operating-level SLA, không phải target.
    lookup_slo_seconds: float = Field(
        default=3.0,
        description="P95 lookup end-to-end latency budget. >ngưỡng → SLO violation.",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def chirpstack_webhook_token_map(self) -> dict[str, UUID]:
        """Parse `chirpstack_webhook_tokens` env → {token: uploader_uuid}.

        Pair sai format hoặc UUID không hợp lệ → bị bỏ qua âm thầm
        (start-up không fail vì 1 dòng env xấu, log đã bắn ở chỗ kiểm tra).
        """
        out: dict[str, UUID] = {}
        for entry in self.chirpstack_webhook_tokens.split(","):
            s = entry.strip()
            if not s or ":" not in s:
                continue
            token, uid = s.split(":", 1)
            token = token.strip()
            if not token:
                continue
            try:
                out[token] = UUID(uid.strip())
            except ValueError:
                continue
        return out


def get_settings() -> Settings:
    return Settings()
