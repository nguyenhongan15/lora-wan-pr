"""Application config — 12-Factor F3 (env-only).

KHÔNG hardcode default cho secrets. Default chỉ cho dev convenience.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator
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
        description=(
            "Comma-separated strict origin whitelist (xem rule-design-cors.md). "
            "WILDCARD '*' bị reject vì allow_credentials=True (plan-auth-v2)."
        ),
    )

    @field_validator("cors_allowed_origins")
    @classmethod
    def _no_cors_wildcard(cls, v: str) -> str:
        # Plan-auth-v2 CORS rule: STRICTLY WHITELISTED ORIGINS. Cookie refresh
        # yêu cầu allow_credentials=True; spec CORS cấm pair "*" + credentials.
        # Reject ngay startup thay vì để browser silently fail trên prod.
        if "*" in v:
            raise ValueError(
                "CORS_ALLOWED_ORIGINS không được chứa '*' — cần whitelist tường minh "
                "vì allow_credentials=True. Liệt kê đầy đủ origin (vd https://app.example.com)."
            )
        return v

    # ── Identity (plan-auth-v1 §3.1 + plan-auth-v2 step 2) ────────────────
    # Required: app fail-fast nếu thiếu, không có dev fallback. Ai cũng có
    # thể gen `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
    jwt_secret: str = Field(
        ...,
        min_length=32,
        description="HS256 signing key cho access token. Bắt buộc — không default.",
    )
    # Short-lived access token theo "Short-Lived JWTs with Revocable Refresh
    # Tokens". 15 phút là sweet spot: đủ ngắn để limit token-theft window, đủ
    # dài để client không phải refresh quá thường xuyên.
    access_ttl_minutes: int = Field(
        default=15,
        ge=1,
        le=1440,
        description="Access JWT TTL (phút). Short-lived per plan-auth-v2.",
    )
    refresh_ttl_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Refresh token TTL (ngày). Rotation-on-use + family revocation.",
    )

    # ── Refresh cookie (plan-auth-v2 step 2) ──────────────────────────────
    # HttpOnly + Secure + SameSite=Lax + path scope. Secure default False để
    # local dev (http://localhost) hoạt động; production .env override =True.
    refresh_cookie_secure: bool = Field(
        default=False,
        description="Set-Cookie Secure flag. TRUE bắt buộc cho production (HTTPS).",
    )
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = Field(
        default="lax",
        description="Set-Cookie SameSite. 'lax' đủ chống CSRF cho POST endpoints.",
    )

    @field_validator("refresh_cookie_samesite", mode="before")
    @classmethod
    def _samesite_valid(cls, v: str) -> str:
        if v.lower() not in ("lax", "strict", "none"):
            raise ValueError("refresh_cookie_samesite phải là lax|strict|none")
        return v.lower()

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

    # ── Super admin (single account) ──────────────────────────────────────
    # Tài khoản admin cấp cao nhất — duy nhất được phép cấp/thu hồi quyền
    # admin + khoá tài khoản. Khi rename email, đổi env var rồi restart.
    super_admin_email: str = Field(
        default="anngh2004@gmail.com",
        description="Email của tài khoản super admin.",
    )

    ml_model_version: str = Field(default="stage1-itu-p1812-v0.1.0")

    # ── Stage 1 path-loss profile (12F III) ──────────────────────────────
    # One of: urban | suburban | rural. Allowlist enforce ở boundary
    # `resolve_environment_profile()` (application/path_loss.py).
    # Lưu ý: ITU-R P.1812 KHÔNG dùng exponent — profile giờ chỉ giữ shadow
    # fading σ cho Confidence.aleatoric_variance_db2.
    lora_env_profile: str = Field(
        default="suburban",
        description="Path loss environment profile: urban|suburban|rural.",
    )

    # ── Stage 1 ITU-R P.1812 + P.2108 backend (crc-covlib) ───────────────
    # dem_directory: path tới folder chứa Copernicus GLO-30 GeoTIFF tiles.
    # Bắt buộc — không default vì layout deployment khác nhau
    # (dev local: E:/DATN/lora-data/dem; container: /var/lib/lora/dem).
    lora_dem_directory: str = Field(
        ...,
        description="Folder chứa DEM GeoTIFF tiles cho ITU-R P.1812 (Copernicus GLO-30).",
    )
    # Surface DEM (DTM + building heights). Rỗng = reuse terrain dir → P.1812
    # chạy như chưa có DSM (clutter qua P.2108 thôi). Set để bật ITU-R P.1812
    # mode P1812_USE_SURFACE_ELEV_DATA với building obstruction thật.
    lora_surface_dem_directory: str = Field(
        default="",
        description="Folder chứa Surface DEM (DTM+buildings) GeoTIFF tiles. Rỗng = reuse terrain.",
    )
    lora_itu_percent_time: float = Field(
        default=50.0,
        gt=0.0,
        le=100.0,
        description="P.1812 percent_time (1..100). 50 = median, 95 = worst-case design.",
    )
    lora_itu_percent_location: float = Field(
        default=50.0,
        gt=0.0,
        le=100.0,
        description="P.1812/P.2108 percent_location. Đối xứng cho cả 2 model.",
    )

    # ── Bidirectional link budget device defaults (Stage 1 v0) ───────────
    # Áp dụng khi PredictRequest không gửi field tương ứng. Cho phép operator
    # tune theo dòng device chủ đạo của triển khai (vd cảm biến nông nghiệp
    # rời antenna 3 dBi vs PCB 0 dBi). tx_power capped 14 dBm bởi domain
    # validation (AS923-2 cap) — đặt > 14 sẽ raise tại Target boundary.
    default_device_tx_power_dbm: float = Field(
        default=14.0,
        ge=-10.0,
        le=14.0,
        description="Device EIRP fallback khi request không gửi tx_power_dbm.",
    )
    default_device_tx_antenna_gain_dbi: float = Field(
        default=2.0,
        ge=-10.0,
        le=30.0,
        description="Device TX antenna gain fallback (dBi).",
    )
    default_device_rx_antenna_gain_dbi: float = Field(
        default=0.0,
        ge=-10.0,
        le=30.0,
        description="Device RX antenna gain fallback (dBi). 0 = PCB integrated.",
    )

    # ── Auth rate limits + lockout (plan-auth-v2 step 1) ─────────────────
    # slowapi-style strings: "<count>/<period>" (period: second|minute|hour|day).
    # Key = client IP (X-Forwarded-For aware nếu deploy sau reverse proxy).
    auth_login_rate_limit: str = Field(
        default="10/minute",
        description="Rate limit cho POST /auth/login per IP.",
    )
    auth_register_rate_limit: str = Field(
        default="5/hour",
        description="Rate limit cho POST /auth/register per IP (chống spam account).",
    )
    # Lockout per email (không per IP — IP bypass dễ qua VPN, email là resource
    # bị attack). Tradeoff: attacker có thể DoS lock victim's email — chấp nhận
    # vì window 15 min ngắn + đã có IP rate-limit ở tầng trên.
    login_lockout_max_attempts: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Số lần sai password liên tiếp trước khi lock account.",
    )
    login_lockout_window_minutes: int = Field(
        default=15,
        ge=1,
        le=1440,
        description="Thời gian lock (phút) sau khi vượt max_attempts.",
    )

    # ── Password reset (pre-deploy checklist §2) ─────────────────────────
    # TTL ngắn (30 phút) — link chỉ dùng được trong cửa sổ hẹp. Token
    # single-use enforce ở SQL; xem migration 0016.
    password_reset_ttl_minutes: int = Field(
        default=30,
        ge=5,
        le=1440,
        description="TTL (phút) cho password reset token. Khuyến nghị 15-60.",
    )
    # Frontend URL template — `{token}` được replace bằng plaintext token.
    # FE đọc query param `?reset=<token>` và mở ResetPassword form. Tách
    # khỏi `webhook_base_url` vì 2 origin khác nhau (FE vs API).
    password_reset_url_template: str = Field(
        default="http://localhost:5173/?reset={token}",
        description="Template URL trong email. {token} sẽ được thay bằng plaintext token.",
    )
    auth_password_reset_request_rate_limit: str = Field(
        default="5/hour",
        description="Rate limit cho POST /auth/password-reset/request per IP.",
    )
    auth_password_reset_confirm_rate_limit: str = Field(
        default="10/hour",
        description="Rate limit cho POST /auth/password-reset/confirm per IP.",
    )

    # ── Email verification (community contribution gate) ──────────────────
    # Khác password reset: TTL dài hơn (60 phút) vì user có thể delay click
    # link. Single-use enforced ở SQL layer (migration 0019).
    email_verification_ttl_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="TTL (phút) cho email verification token.",
    )
    email_verification_url_template: str = Field(
        default="http://localhost:5173/?verify_email={token}",
        description="Template URL trong email. {token} sẽ được thay bằng plaintext token.",
    )
    auth_email_verify_request_rate_limit: str = Field(
        default="5/hour",
        description="Rate limit cho POST /auth/email-verify/request per user.",
    )
    auth_email_verify_confirm_rate_limit: str = Field(
        default="10/hour",
        description="Rate limit cho POST /auth/email-verify/confirm per IP.",
    )

    # ── SMTP (password reset mailer) ─────────────────────────────────────
    # Empty host = NoOpMailer (dev: reset URL log ra console, không gửi).
    # Production: validator dưới chặn empty + warn nếu from_email default.
    smtp_host: str = Field(
        default="",
        description="SMTP server hostname. Empty = NoOpMailer (dev/test).",
    )
    smtp_port: int = Field(
        default=587,
        ge=1,
        le=65535,
        description="SMTP server port. 587 STARTTLS (Gmail/SES); 1025 dev mailpit.",
    )
    smtp_username: str = Field(
        default="",
        description="SMTP login username. Empty = unauthenticated (mailpit/local).",
    )
    smtp_password: str = Field(
        default="",
        description="SMTP login password.",
    )
    smtp_from_email: str = Field(
        default="noreply@lora-coverage.local",
        description="From: address. Production phải khớp domain verified ở provider.",
    )
    smtp_from_name: str = Field(
        default="LoRa Coverage",
        description="From: display name.",
    )
    smtp_use_starttls: bool = Field(
        default=True,
        description="STARTTLS upgrade sau khi connect. False cho local mailpit.",
    )

    # ── Coverage endpoint rate limits (per IP) ───────────────────────────
    # Public read endpoints — không có auth gate nhưng compute đắt:
    #   * /predict: ITU-R P.1812 + crc-covlib (~hundreds ms / call).
    #   * /lookup:  geocode (external HTTP) + predict, SLO P95 < 3s.
    #   * /batch:   ≤500 item × predict mỗi item → potential 8 phút CPU.
    # Không decorator = unlimited; 1 IP loop endpoint = cloud bill / DoS.
    #
    # /batch cost-amplification tradeoff: limit count theo request, không theo
    # item. Với cap 500 item/req: 1/min × 500 = 500 predict/min/IP (vẫn ~16×
    # /predict). Cap thấp 1/min vì:
    #   (a) UI BulkLookup là one-shot CSV upload, không cần liên tục.
    #   (b) Cost symmetry thật sự cần per-item weighting (slowapi không support
    #       native) hoặc auth-gated user quota — defer khi /batch require login.
    coverage_predict_rate_limit: str = Field(
        default="30/minute",
        description="Rate limit cho POST /coverage/predict per IP.",
    )
    coverage_lookup_rate_limit: str = Field(
        default="30/minute",
        description="Rate limit cho POST /coverage/lookup per IP (geocode + predict).",
    )
    coverage_batch_rate_limit: str = Field(
        default="1/minute",
        description="Rate limit cho POST /coverage/batch per IP (≤500 item/req).",
    )
    # CSV upload tốn DB insert + ITU compute mỗi row khi submit_to_community
    # → cap thấp. User chỉ upload survey log định kỳ; 10/hour đủ flexibility.
    me_csv_upload_rate_limit: str = Field(
        default="10/hour",
        description="Rate limit cho POST /me/uploads/csv per user (CSV survey upload).",
    )

    # ── Rate-limit storage (Chapter 4 §Distributed Environments) ─────────
    # Empty = in-memory per worker (dev / single-worker test). Production
    # PHẢI set redis://host:port/db để workers chia sẻ counter — nếu không
    # effective limit = n_workers × ngưỡng config (state divergence). Format
    # theo `limits` library: redis|memcached|mongodb://... — xem
    # https://limits.readthedocs.io/en/stable/storage.html.
    rate_limit_storage_uri: str = Field(
        default="",
        description="URI store cho rate-limit counter. Rỗng = in-memory. Prod: redis://cache:6379/0.",
    )

    @model_validator(mode="after")
    def _rate_limit_storage_required_in_prod(self) -> Settings:
        # Fail-fast giống _webhook_base_url_required_in_prod: prod không có
        # shared store → silent multi-worker divergence khó debug, để
        # operator phát hiện tại startup chứ không phải tại incident.
        if self.app_env == "production" and not self.rate_limit_storage_uri:
            raise ValueError(
                "RATE_LIMIT_STORAGE_URI bắt buộc khi APP_ENV=production — "
                "in-memory storage không sync giữa workers, rate-limit effective "
                "sẽ là (n_workers × ngưỡng). Đặt ví dụ: "
                "RATE_LIMIT_STORAGE_URI=redis://cache:6379/0"
            )
        return self

    # ── Gateway state cache (online/offline từ ChirpStack) ───────────────
    # Service GatewayStateService gọi ChirpStack ListGateways mỗi request
    # /api/v1/gateways sẽ slow + tải ChirpStack. Cache state map vào Valkey
    # với TTL ngắn. Rỗng = disable cache (mỗi request gọi thẳng — fine ở dev).
    # Default trỏ vào Valkey db=3 (db 0 rate-limit, 1 celery broker, 2 celery
    # backend — db 3 dedicated cho gateway state).
    gateway_state_cache_url: str = Field(
        default="redis://cache:6379/3",
        description="Redis URL cache gateway state. Rỗng = disable cache.",
    )
    gateway_state_cache_ttl_s: int = Field(
        default=60,
        description="TTL (giây) cho gateway state cache. Default 60.",
    )
    # Khi /predict chọn serving gateway: chỉ xét gateway còn HOẠT ĐỘNG gần đây
    # (có uplink/survey trong N ngày) → tránh chọn gateway đã chết (vd tắt từ
    # nhiều tháng) mà thiết bị thật không thể kết nối. 0 = tắt filter (xét mọi
    # public gw). Nếu filter loại sạch → fallback xét tất cả (không để rỗng).
    # Nguồn hoạt động: MAX(ts.survey_training.timestamp) per gateway (cùng tín
    # hiệu GatewayStateService dùng). Default 90 ngày (loại gw chết >3 tháng,
    # chịu được khảo sát thưa).
    gateway_active_window_days: int = Field(
        default=90,
        ge=0,
        description="Cửa sổ (ngày) coi gateway còn sống cho việc chọn serving gw. 0 = tắt.",
    )

    # ── Celery (admin rebuild coverage map task) ─────────────────────────
    # Broker + result backend đều trỏ vào Valkey (cache service) — DB khác
    # với rate-limit (/0) để né collision LRU. KHÔNG dùng /0 vì rate-limit
    # counter eviction có thể kick state Celery (allkeys-lru policy).
    celery_broker_url: str = Field(
        default="redis://cache:6379/1",
        description="Celery broker (Redis-compatible). Default trỏ vào Valkey cache db=1.",
    )
    celery_result_backend: str = Field(
        default="redis://cache:6379/2",
        description="Celery result backend (Redis-compatible). Valkey cache db=2.",
    )

    # ── Sentry error tracking (pre-deploy checklist §8) ──────────────────
    # Rỗng = init no-op (dev / chưa cấu hình); structlog stdout vẫn ghi
    # errors. Production set DSN để long-tail single-user crash không lọt
    # qua Prometheus rate/latency metrics. tracesSampleRate giữ 0 — chỉ ghi
    # exception, không trace performance (cost-aware default).
    sentry_dsn: str = Field(
        default="",
        description="Sentry DSN cho api-service. Rỗng = disabled.",
    )
    sentry_traces_sample_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Tỉ lệ sample performance trace. Mặc định 0 = chỉ ghi exception.",
    )

    # ── ChirpStack per-user webhook ingest ────────────────────────────────
    # Plan ChirpStack per-user webhook ingest. Legacy env-map
    # `chirpstack_webhook_tokens` đã remove — DB-backed per-user token
    # (auth.linked_sources.webhook_token_hash). Admin/user re-link sau deploy
    # để được cấp URL mới.
    chirpstack_webhook_rate_limit: str = Field(
        default="600/minute",
        description=(
            "Rate limit cho POST /webhooks/chirpstack/source/{token} per token. "
            "ChirpStack v4 mặc định không vượt 100 msg/s/app; 600/minute là trần "
            "thoải mái cho deployment đơn ứng dụng vài chục device."
        ),
    )
    # FE build webhook URL hiển thị cho user copy paste vào ChirpStack HTTP
    # Integration. Phải là origin public-facing (vd https://api.example.com),
    # KHÔNG được rỗng ở production — validator chặn từ startup.
    webhook_base_url: str = Field(
        default="",
        description=(
            "Public base URL của API (vd https://api.example.com). FE concat "
            "với '/api/v1/webhooks/chirpstack/source/<token>' để ra URL đầy đủ. "
            "Bắt buộc cho app_env=production."
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

    # ── Stage 2 ML end-to-end (Predict-ML) ────────────────────────────────
    # base_url rỗng → Stage 2 disabled (Stage1-only response). Khi set + có
    # active model, mọi /predict + /lookup được refine bằng delta (residual_db)
    # do ml-service trả về.
    stage2_predict_base_url: str = Field(
        default="",
        description="Internal URL tới ml-service (vd http://ml-service:8001). Rỗng = disabled.",
    )
    stage2_auth_token: str = Field(
        default="",
        description="Bearer token gửi tới ml-service. Phải khớp LORA_STAGE2_AUTH_TOKEN bên ml-service.",
    )
    stage2_timeout_seconds: float = Field(
        default=3.0,
        ge=0.05,
        le=5.0,
        description="Per-request timeout. Quá thời gian → fallback Stage1. "
        "Extra Trees làm DEM + OSM lookup + 30m step Fresnel; default 3s để "
        "có headroom.",
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

    @model_validator(mode="after")
    def _webhook_base_url_required_in_prod(self) -> Settings:
        if self.app_env == "production" and not self.webhook_base_url:
            raise ValueError(
                "WEBHOOK_BASE_URL bắt buộc khi APP_ENV=production — FE cần "
                "origin public-facing để build URL hiển thị cho user. "
                "Đặt ví dụ: WEBHOOK_BASE_URL=https://api.example.com"
            )
        return self

    @model_validator(mode="after")
    def _smtp_required_in_prod(self) -> Settings:
        # NoOpMailer trong production = silent failure khi user yêu cầu
        # reset password (log only). Operator phải biết để wire SMTP thật.
        if self.app_env == "production" and not self.smtp_host:
            raise ValueError(
                "SMTP_HOST bắt buộc khi APP_ENV=production — không có SMTP "
                "thì password reset email không gửi được, user bị khoá ngoài. "
                "Wire SES/Gmail SMTP hoặc set APP_ENV=development để dùng "
                "NoOpMailer (log URL ra console)."
            )
        return self

    @model_validator(mode="after")
    def _password_reset_url_template_valid(self) -> Settings:
        # Lỗi typo "{tokeN}" → format silent-substitute không ra URL hợp lệ.
        # Catch tại startup chứ không phải lúc user click link.
        if "{token}" not in self.password_reset_url_template:
            raise ValueError(
                "PASSWORD_RESET_URL_TEMPLATE phải chứa placeholder '{token}'. "
                "Ví dụ: https://app.example.com/?reset={token}"
            )
        return self

    @model_validator(mode="after")
    def _email_verification_url_template_valid(self) -> Settings:
        if "{token}" not in self.email_verification_url_template:
            raise ValueError(
                "EMAIL_VERIFICATION_URL_TEMPLATE phải chứa placeholder '{token}'. "
                "Ví dụ: https://app.example.com/?verify_email={token}"
            )
        return self


def get_settings() -> Settings:
    return Settings()
