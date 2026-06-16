"""Pydantic v2 request/response schemas.

KHÔNG expose ORM models. Schema riêng cho edge layer (theo
rule-design-restfulapi.md §6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── Coverage prediction ───────────────────────────────────────────────────


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    latitude: float = Field(..., ge=-90, le=90, examples=[16.0544])
    longitude: float = Field(..., ge=-180, le=180, examples=[108.2022])
    spreading_factor: int = Field(..., ge=7, le=12, examples=[7])
    frequency_mhz: float = Field(default=923.0, examples=[923.0])
    # Bidirectional link budget device-side overrides. None → fallback Settings
    # default ở router. tx_power_dbm capped 14 dBm theo AS923-2 regional params.
    tx_power_dbm: float | None = Field(default=None, ge=-10, le=14)
    tx_antenna_gain_dbi: float | None = Field(default=None, ge=-10, le=30)
    rx_antenna_gain_dbi: float | None = Field(default=None, ge=-10, le=30)
    rx_sensitivity_dbm: float | None = Field(default=None, ge=-150, le=-50)
    # Terminal environment — outdoor = no BEL; indoor/indoor_deep apply
    # ITU-R P.2109 building entry loss (traditional building, prob 50%/90%).
    environment: Literal["outdoor", "indoor", "indoor_deep"] = "outdoor"


class ConfidenceResponse(BaseModel):
    score: float = Field(..., ge=0, le=1)
    method: Literal["physics", "residual", "ensemble", "bayesian"]
    # Variance components (dB²). Stage 1 set aleatoric từ shadow fading σ²;
    # epistemic = 0. Stage 2/3 sẽ điền epistemic từ ensemble/posterior.
    # Tổng σ = √(epistemic + aleatoric) → FE dùng làm "sai số" (±σ ~ 68% CI,
    # ±1.96σ ~ 95% CI Gaussian).
    epistemic_variance_db2: float = Field(default=0.0, ge=0)
    aleatoric_variance_db2: float = Field(default=0.0, ge=0)


class LinkBudgetResponse(BaseModel):
    """Per-direction link budget (UL hoặc DL)."""

    model_config = ConfigDict(extra="forbid")

    rssi_dbm: float
    snr_db: float
    margin_db: float  # rssi - rx_sensitivity (>0 = decodable)
    status: Literal["strong", "marginal", "weak", "no_coverage"]


class SignalQualityResponse(BaseModel):
    """Các chỉ số chất lượng tín hiệu suy ra cho UI "Dự đoán điểm".

    PDR/BER/FER suy từ SNR margin (LoRa CSS waterfall) → tự cập nhật khi Stage 2
    ML shift SNR. ToA/jitter/bandwidth là MAC-layer params đối xứng UL/DL.
    Noise floor: UL = per-gateway calibrated; DL = thermal -117 dBm.
    """

    model_config = ConfigDict(extra="forbid")

    pdr: float = Field(..., ge=0, le=1)
    ber: float = Field(..., ge=0)
    fer: float = Field(..., ge=0, le=1)
    bandwidth_hz: int = Field(..., gt=0)
    time_on_air_ms: float = Field(..., ge=0)
    jitter_ms: float = Field(..., ge=0)
    shadow_fading_sigma_db: float = Field(..., ge=0)
    uplink_noise_floor_dbm: float
    downlink_noise_floor_dbm: float


class EnvironmentParamsResponse(BaseModel):
    """Echo "Thông số môi trường ảnh hưởng" — input đã dùng để tính prediction."""

    model_config = ConfigDict(extra="forbid")

    frequency_mhz: float
    tx_power_dbm: float
    environment: Literal["outdoor", "indoor", "indoor_deep"]
    spreading_factor: int = Field(..., ge=7, le=12)


class PredictionResponse(BaseModel):
    # rssi_dbm/snr_db giữ nghĩa = downlink để backward compat (clients vẽ marker
    # từ field này). coverage_status = worst-of(uplink, downlink).
    rssi_dbm: float
    snr_db: float
    coverage_status: Literal["strong", "marginal", "weak", "no_coverage"]
    serving_gateway_id: UUID | None
    confidence: ConfidenceResponse
    model_version: str
    recommended_sf: int = Field(..., ge=7, le=12)
    uplink: LinkBudgetResponse
    downlink: LinkBudgetResponse
    # Path loss tổng (basic transmission loss + BEL nếu có); UL/DL đối xứng.
    path_loss_db: float = 0.0
    # Khoảng cách haversine target → serving gateway (km). 0.0 = no serving GW.
    distance_to_serving_gateway_km: float = 0.0
    # Chỉ số chất lượng tín hiệu + tham số môi trường (UI "Dự đoán điểm").
    signal_quality: SignalQualityResponse
    environment_params: EnvironmentParamsResponse
    # Số gateway có status != NO_COVERAGE trong 30 km radius (redundancy metric).
    # 1 = single point of failure; ≥2 = diversity. 0 hợp lệ khi NO_COVERAGE.
    covering_gateway_count: int = Field(default=0, ge=0)
    # Root-cause flags của bottleneck — 5 cause compute được từ Stage 1/2 + Target.
    # Rỗng = không cause nào chạm threshold (link healthy hoặc cân bằng).
    bottleneck_causes: list[
        Literal[
            "path_loss_high",
            "snr_low",
            "interference",
            "tx_power_cap",
            "sf_mismatch",
        ]
    ] = Field(default_factory=list)


# ── Health ────────────────────────────────────────────────────────────────


class HealthStatus(BaseModel):
    status: Literal["ok", "degraded"]
    version: str


# ── Problem details (RFC 7807) ────────────────────────────────────────────


class ProblemDetails(BaseModel):
    """RFC 7807 Problem Details."""

    model_config = ConfigDict(populate_by_name=True)

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str | None = None
    trace_id: str | None = Field(default=None, alias="traceId")


# ── Gateway directory ─────────────────────────────────────────────────────


class GatewayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    name: str
    latitude: float
    longitude: float
    altitude_m: float
    antenna_height_m: float
    antenna_gain_dbi: float  # TX gain
    tx_power_dbm: float
    frequency_mhz: float
    # rx_antenna_gain_dbi None = duplex symmetric; rx_sensitivity_dbm None =
    # derive từ SF table ở application layer.
    # noise_floor_dbm None = fallback DEFAULT_NOISE_FLOOR_DBM ở app layer.
    rx_antenna_gain_dbi: float | None = None
    rx_sensitivity_dbm: float | None = None
    noise_floor_dbm: float | None = None
    # Live state — ChirpStack ưu tiên (real-time); fallback derive từ
    # MAX(survey_training.timestamp) per gateway (window 5 phút = online).
    # "unknown" = cả 2 nguồn fail; never_seen = chưa có packet nào.
    state: Literal["online", "offline", "never_seen", "unknown"] = "unknown"
    last_seen_at: datetime | None = None
    # is_public=False → admin ẩn khỏi bản đồ chung; vẫn hiện ở "Của tôi".
    is_public: bool = True
    # Admin "ghim" trạng thái thủ công (mig 0033). Khi non-null, _to_response
    # trả luôn state này thay vì derived từ ChirpStack + survey_training.
    manual_state_override: Literal["online", "offline", "never_seen"] | None = None


class GatewayListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[GatewayResponse]
    total: int


class GatewayCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(..., min_length=3, max_length=64, examples=["DAD-012"])
    name: str = Field(..., min_length=1, max_length=255)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    altitude_m: float = Field(default=0.0)
    antenna_height_m: float = Field(default=10.0, ge=0)
    antenna_gain_dbi: float = Field(default=2.0)  # TX gain
    tx_power_dbm: float = Field(default=14.0, ge=-10, le=30)
    # mypy: Python's Literal[...] không chính thức hỗ trợ float, nhưng
    # Pydantic v2 validate đúng runtime + sinh OpenAPI enum đúng.
    # Tham khảo: https://docs.pydantic.dev/latest/concepts/types/#literal
    frequency_mhz: Literal[433.0, 868.0, 915.0, 923.0] = 923.0  # type: ignore[valid-type]
    rx_antenna_gain_dbi: float | None = Field(default=None, ge=-10, le=30)
    rx_sensitivity_dbm: float | None = Field(default=None, ge=-150, le=-50)
    noise_floor_dbm: float | None = Field(default=None, ge=-130, le=-80)


class GatewayPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    altitude_m: float | None = None
    antenna_height_m: float | None = Field(default=None, ge=0)
    antenna_gain_dbi: float | None = None
    tx_power_dbm: float | None = Field(default=None, ge=-10, le=30)
    is_public: bool | None = None
    rx_antenna_gain_dbi: float | None = Field(default=None, ge=-10, le=30)
    rx_sensitivity_dbm: float | None = Field(default=None, ge=-150, le=-50)
    noise_floor_dbm: float | None = Field(default=None, ge=-130, le=-80)
    # null = clear override (về derived state); literal = ghim trạng thái.
    # Extra-forbid + sentinel-explicit nên cần phân biệt "không gửi" vs "gửi null":
    # router patch dict chỉ apply key khi explicit set ở body.
    manual_state_override: Literal["online", "offline", "never_seen"] | None = None


# ── Survey training (read-only) ───────────────────────────────────────────


class SurveyTrainingPointResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float
    longitude: float
    rssi_dbm: float
    snr_db: float
    spreading_factor: int
    serving_gateway_id: UUID | None
    device_id: str | None
    frequency_mhz: float
    timestamp: datetime
    code_rate: str | None


class SurveyTrainingListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SurveyTrainingPointResponse]
    total: int


class MyDeviceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    count: int = Field(..., ge=0)


class MyDeviceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MyDeviceItem]


# ── ChirpStack webhook ────────────────────────────────────────────────────


class WebhookIngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_count: int = Field(..., ge=0)
    inserted_count: int = Field(..., ge=0)
    rejected_count: int = Field(..., ge=0)
    rejected_reasons: list[str] = Field(default_factory=list)


# ── CSV upload (plan community-data-contribution §4) ──────────────────────


class CsvUploadResponse(BaseModel):
    """Per-row outcome sau parse + ingest. Refactor 2026-06-11: upload luôn
    private; user bấm "Đóng góp" trên 1 batch riêng để gửi admin duyệt nên
    không còn `promoted_count` / `promote_rejected_*`.

    `parse_rejected_count` = row bị adapter loại (sai schema, RSSI ngoài
    range, gateway_code không tồn tại). `inserted_count` = row thực sự vào
    quarantine (sau ON CONFLICT DO NOTHING). `batch_id` = id row mới trong
    `me.upload_batches`; None khi parsed_count=0 (không tạo batch rỗng).
    """

    model_config = ConfigDict(extra="forbid")

    batch_id: UUID | None = None
    parsed_count: int = Field(..., ge=0)
    parse_rejected_count: int = Field(..., ge=0)
    parse_rejected_reasons: list[str] = Field(default_factory=list)
    inserted_count: int = Field(..., ge=0)


# ── Upload batches (mig 0024 + refactor 2026-06-11) ───────────────────────
# 1 batch = 1 lần "bắn data": upload file (csv/json) hoặc click "Tải dữ liệu
# mới nhất" trên linked source (sync_lpwanmapper/sync_chirpstack). Trạng thái
# suy ra ở backend (UploadBatchSummary.status), FE không tự tính.


UploadKindLiteral = Literal["csv", "json", "sync_lpwanmapper", "sync_chirpstack", "live_session"]
BatchStatusLiteral = Literal["private", "pending", "public", "rejected", "deleted"]


class UploadBatchItem(BaseModel):
    """1 row trong bảng "Quản lý dữ liệu" / "Lịch sử upload"."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: UploadKindLiteral
    filename: str
    linked_source_id: UUID | None
    uploaded_at: datetime
    points_count: int = Field(..., ge=0)
    status: BatchStatusLiteral
    deleted_at: datetime | None = None


class UploadBatchListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[UploadBatchItem] = Field(default_factory=list)


class UploadOverviewResponse(BaseModel):
    """Tổng quan card "Tổng quan" trên trang "Dữ liệu của tôi" (chỉ batch
    chưa xoá). Số batches/points cũng đếm theo trạng thái suy diễn."""

    model_config = ConfigDict(extra="forbid")

    batches_total: int = Field(..., ge=0)
    points_total: int = Field(..., ge=0)
    public_batches: int = Field(..., ge=0)
    pending_batches: int = Field(..., ge=0)
    private_batches: int = Field(..., ge=0)


class UploadBatchSubmitResponse(BaseModel):
    """Đóng góp 1 batch → admin duyệt. `queued` = số rows mới chuyển
    pending_review trong call này (idempotent: re-call → 0)."""

    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    queued: int = Field(..., ge=0)


class UploadBatchDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    deleted: bool


# ── Address lookup (F2 funnel) ────────────────────────────────────────────


class AddressLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    address: str = Field(
        ...,
        min_length=1,
        max_length=500,
        examples=[
            "Số 1 Lý Thường Kiệt, Hải Châu, Đà Nẵng",
        ],
    )
    spreading_factor: int = Field(default=7, ge=7, le=12)
    frequency_mhz: Literal[433.0, 868.0, 915.0, 923.0] = 923.0  # type: ignore[valid-type]


class ResolvedAddressResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float
    longitude: float
    display_name: str
    provider: Literal["cache", "nominatim", "vietmap", "goong", "google"]
    confidence: float = Field(..., ge=0, le=1)


class CoverageLookupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: ResolvedAddressResponse
    prediction: PredictionResponse


# ── Coverage batch (bulk lookup, F3 § /coverage/batch) ────────────────────


class CoverageBatchItem(BaseModel):
    """Mỗi phần tử là một input đơn — có thể là address text hoặc tọa độ."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class CoverageBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CoverageBatchItem] = Field(..., min_length=1, max_length=500)
    spreading_factor: int = Field(default=7, ge=7, le=12)
    frequency_mhz: Literal[433.0, 868.0, 915.0, 923.0] = 923.0  # type: ignore[valid-type]


class CoverageBatchItemResult(BaseModel):
    """Per-item kết quả. status="ok" → có prediction; "error" → có error."""

    model_config = ConfigDict(extra="forbid")

    label: str | None
    status: Literal["ok", "error"]
    address: ResolvedAddressResponse | None = None
    prediction: PredictionResponse | None = None
    error_code: str | None = None
    error_message: str | None = None


class CoverageBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CoverageBatchItemResult]
    ok_count: int
    error_count: int


# ── Auth (plan-auth-v1 §3.1) ──────────────────────────────────────────────
# Email regex chỉ check shape tối thiểu (có '@', có TLD). Validation thật
# nằm ở DB unique constraint + (v2) email verification flow.

_EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(..., min_length=3, max_length=320, pattern=_EMAIL_PATTERN)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    is_admin: bool
    is_super_admin: bool = False
    email_verified: bool
    created_at: datetime


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: Literal["bearer"]
    expires_at: datetime


# ── Password reset (pre-deploy checklist §2) ──────────────────────────────


class PasswordResetRequestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(..., min_length=3, max_length=320, pattern=_EMAIL_PATTERN)


class PasswordResetConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # 43-char base64url token = secrets.token_urlsafe(32). Pattern check
    # shape để 422 fast trên junk input thay vì tốn DB query.
    token: str = Field(..., min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_\-]+$")
    new_password: str = Field(..., min_length=8, max_length=128)


# ── Email verification ────────────────────────────────────────────────────


class EmailVerifyConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    token: str = Field(..., min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_\-]+$")


# ── Linking — me/sources (plan-auth-v1 §3.3) ──────────────────────────────


class LinkSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # source_type whitelist enforce qua sources.get_adapter() ở service layer
    # (raise UnknownSourceTypeError → 400). Schema chỉ check shape.
    source_type: str = Field(..., min_length=1, max_length=64, examples=["lpwanmapper"])
    label: str = Field(..., min_length=1, max_length=100, examples=["Cá nhân"])
    # Adapter-specific dict; mỗi adapter document required keys ở docstring
    # connect(). Schema không validate shape vì sẽ khác giữa lpwanmapper /
    # chirpstack / csv. service.test() validate bằng cách thử connect().
    credentials: dict[str, str] = Field(..., min_length=1)


class LinkedSourcePatchRequest(BaseModel):
    """Partial update — chỉ field `status` được apply.

    `status` chỉ accept 'active'/'paused' từ API; 'failed' do sync
    orchestrator set nội bộ (Step 7).
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "paused"] | None = None


class LinkedSourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_type: str
    label: str
    status: Literal["active", "paused", "failed"]
    last_sync_at: datetime | None
    last_sync_error: str | None
    created_at: datetime
    # Webhook columns expose presence-only (plan ChirpStack per-user webhook
    # ingest §1 "show-once"). Plaintext token CHỈ trả qua LinkSourceCreatedResponse
    # tại link/rotate, không bao giờ trong list endpoint.
    has_webhook_token: bool = False
    webhook_rotated_at: datetime | None = None


class LinkedSourceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LinkedSourceResponse]
    total: int


class LinkSourceCreatedResponse(BaseModel):
    """Response của POST /me/sources khi link source thành công.

    Plan ChirpStack per-user webhook ingest: source thuộc whitelist (hiện
    chỉ chirpstack) → backend cấp `webhook_url` + `webhook_token` plaintext
    KÈM 1 LẦN DUY NHẤT trong response này. Sau đó FE muốn xem = phải rotate.
    Source khác (lpwanmapper): webhook_url/webhook_token = None.
    """

    model_config = ConfigDict(extra="forbid")

    source: LinkedSourceResponse
    webhook_url: str | None = None
    webhook_token: str | None = None


class WebhookSecretResponse(BaseModel):
    """Response của POST /me/sources/{id}/rotate-webhook.

    Trả plaintext token mới + URL hoàn chỉnh để FE hiển thị 1 lần. Token cũ
    đã invalidate ngay khi response trả về (DB commit xong).
    """

    model_config = ConfigDict(extra="forbid")

    source: LinkedSourceResponse
    webhook_url: str
    webhook_token: str


# ── Devices (synced từ external source) ───────────────────────────────────


class DeviceResponse(BaseModel):
    """geo.devices row projected cho FE list."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    dev_eui: str
    name: str | None
    source_type: str
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeviceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DeviceResponse]
    total: int


# ── Sync (plan-auth-v1 §3.4) ──────────────────────────────────────────────
# `error` non-null = sync thất bại (adapter unreachable / decrypt fail / lock
# busy). HTTP vẫn 200 (plan §3.4 không raise) — caller inspect field này.


class SyncResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    linked_source_id: UUID
    gateways_inserted: int = Field(..., ge=0)
    gateways_updated: int = Field(..., ge=0)
    gateways_quarantined: int = Field(..., ge=0)
    measurements_inserted: int = Field(..., ge=0)
    measurements_updated: int = Field(..., ge=0)
    devices_inserted: int = Field(..., ge=0)
    devices_updated: int = Field(..., ge=0)
    last_sync_at: datetime | None
    error: str | None


class SyncReportResponse(BaseModel):
    """Aggregate kết quả admin global sync (plan §3.4 sync_all_eligible)."""

    model_config = ConfigDict(extra="forbid")

    items: list[SyncResultResponse]
    total: int = Field(..., ge=0)
    successes: int = Field(..., ge=0)
    failures: int = Field(..., ge=0)


# ── Admin (plan-auth-v1 §3.5, §11 step 8) ─────────────────────────────────
# Chỉ admin (is_admin=true) gọi được. Audit log + RFC 7807 errors qua
# AdminRequiredError (403) / AdminSelfModificationError (400).


class UserAdminResponse(BaseModel):
    """User listing cho /admin/users — bao gồm quản lý + thống kê đóng góp."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    is_admin: bool
    is_super_admin: bool = False
    disabled: bool
    created_at: datetime
    contribution_count: int = Field(..., ge=0)


class UserListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[UserAdminResponse]
    total: int = Field(..., ge=0)


class UserPatchRequest(BaseModel):
    """Partial update is_admin / disabled. Cả 2 None → 422.

    Self-modification (admin sửa chính mình) được xử lý ở router thay vì
    schema vì cần biết caller — schema chỉ check shape.
    """

    model_config = ConfigDict(extra="forbid")

    is_admin: bool | None = None
    disabled: bool | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> UserPatchRequest:
        if self.is_admin is None and self.disabled is None:
            raise ValueError("Cần ít nhất 1 trong is_admin hoặc disabled")
        return self


class AdminStatsResponse(BaseModel):
    """Counters tổng cho /admin/stats. Snapshot tại thời điểm query —
    không phải transactional aggregate đối với insert/delete đồng thời.
    """

    model_config = ConfigDict(extra="forbid")

    user_count: int = Field(..., ge=0)
    # "User online" — distinct users co last_seen_at trong 5 phut gan nhat.
    online_user_count: int = Field(..., ge=0)
    active_source_count: int = Field(..., ge=0)
    gateway_count: int = Field(..., ge=0)
    measurement_count: int = Field(..., ge=0)
    pending_review_count: int = Field(..., ge=0)


class PendingContributionResponse(BaseModel):
    """1 row chờ admin duyệt — đã pass auto-validate, đủ field cho map preview."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    timestamp: datetime
    submitted_at: datetime
    latitude: float
    longitude: float
    rssi_dbm: float
    snr_db: float
    spreading_factor: int
    frequency_mhz: float
    source_type: str | None
    contributor_user_id: UUID | None
    contributor_email: str | None
    serving_gateway_id: UUID | None
    gateway_code: str | None
    linked_source_id: UUID | None


class PendingContributionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PendingContributionResponse]
    total: int = Field(..., ge=0)


class PendingReviewBatchResponse(BaseModel):
    """1 batch CSV upload (= 1 file user upload) còn ≥1 row chờ duyệt
    HOẶC ≥1 gateway pending. earliest/latest_timestamp có thể null khi batch
    chỉ có gateway pending mà không có điểm đo chờ duyệt nào."""

    model_config = ConfigDict(extra="forbid")

    uploader_id: UUID
    uploader_email: str | None
    uploaded_at: datetime
    pending_review_count: int = Field(..., ge=0)
    total_count: int = Field(..., ge=0)
    earliest_timestamp: datetime | None = None
    latest_timestamp: datetime | None = None
    new_gateway_count: int = Field(default=0, ge=0)


class PendingReviewBatchListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PendingReviewBatchResponse]


class BatchGatewayResponse(BaseModel):
    """1 gateway trong map preview của batch review.

    is_new=True → gateway pending (chưa vào geo.gateways), id là quarantine.id.
    is_new=False → gateway đã promoted, id là geo.gateways.id.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    name: str | None
    latitude: float
    longitude: float
    frequency_mhz: float
    source_type: str | None
    is_new: bool


class BatchRowsResponse(BaseModel):
    """Response của GET /contributions/batches/rows — gộp cả điểm đo + gateway
    cho map preview. Admin "Xem chi tiết" 1 batch nhận data này."""

    model_config = ConfigDict(extra="forbid")

    points: list[PendingContributionResponse]
    gateways: list[BatchGatewayResponse]
    total_points: int = Field(..., ge=0)
    new_gateway_count: int = Field(..., ge=0)


class BatchReviewRequest(BaseModel):
    """Identifier 1 batch CSV (uploader + uploaded_at). Admin gửi body POST
    cho approve/reject — uploaded_at là ISO 8601 datetime.

    `mode` chỉ dùng cho /approve: "all" (mặc định, duyệt cả file), "points_only"
    (defer điểm trỏ gateway mới), "gateways_only" (promote gateway, reject điểm).
    /reject bỏ qua mode.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    uploader_id: UUID
    uploaded_at: datetime
    note: str | None = Field(default=None, max_length=500)
    mode: Literal["all", "points_only", "gateways_only"] = "all"


class BatchReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uploader_id: UUID
    uploaded_at: datetime
    approved_count: int = Field(default=0, ge=0)
    deferred_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    gateways_approved_count: int = Field(default=0, ge=0)
    gateways_rejected_count: int = Field(default=0, ge=0)


# ── Coverage map rebuild (admin) ────────────────────────────────────────


class CoverageRebuildEnqueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: Literal["queued"]


class CoverageRebuildJobResponse(BaseModel):
    """1 lần admin trigger rebuild RSSI heatmap. per_gw_log JSONB raw từ DB."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    triggered_by: UUID | None
    triggered_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    gateways_total: int | None
    gateways_rebuilt: int
    gateways_skipped: int
    per_gw_log: dict[str, Any]
    error_text: str | None
    celery_task_id: str | None


class CoverageRebuildJobListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CoverageRebuildJobResponse]


# ── Admin training-batch audit (data đã duyệt vào ts.survey_training) ────


class TrainingBatchItem(BaseModel):
    """1 batch upload đã có ≥1 row trong ts.survey_training (đã được admin duyệt).

    Khác `UploadBatchItem` ở user side: kèm `uploader_email` + `latest_approved_at`
    cho admin trace-back.
    """

    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    uploader_id: UUID
    uploader_email: str | None
    uploader_is_admin: bool = False
    uploader_is_super_admin: bool = False
    kind: Literal["csv", "json", "sync_lpwanmapper", "sync_chirpstack", "live_session"] | None
    filename: str | None
    uploaded_at: datetime | None
    promoted_count: int = Field(..., ge=0)
    latest_approved_at: datetime
    batch_deleted_at: datetime | None


class TrainingBatchListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TrainingBatchItem]


class TrainingBatchDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    deleted_count: int


# ── Admin ML retrain (mirror CoverageRebuild*) ───────────────────────────


class MlRetrainEnqueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: Literal["queued"]


class MlRetrainJobResponse(BaseModel):
    """1 lần admin trigger retrain Extra Trees ML model.

    `metrics` JSONB chứa RMSE/MAE/R²/feature_count sau khi train xong;
    `artifact_path` = đường dẫn joblib ml-service đang serve.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    triggered_by: UUID | None
    triggered_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    rows_trained: int | None
    artifact_path: str | None
    metrics: dict[str, Any]
    error_text: str | None
    celery_task_id: str | None
    report_dir: str | None = None


class MlRetrainJobListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MlRetrainJobResponse]


class DataFreshnessResponse(BaseModel):
    """Đếm điểm đo training đã thêm kể từ lần rebuild / retrain thành công gần
    nhất. Frontend hiển thị banner nhắc admin chạy khi vượt ngưỡng.
    """

    model_config = ConfigDict(extra="forbid")

    threshold: int
    last_rebuild_finished_at: datetime | None
    new_points_since_rebuild: int
    needs_rebuild: bool
    last_retrain_finished_at: datetime | None
    new_points_since_retrain: int
    needs_retrain: bool


class TimeseriesPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket_start: datetime
    count: int


class TimeseriesResponse(BaseModel):
    """Time-series chart cho admin dashboard. Buckets đầy đủ (kể cả 0)."""

    model_config = ConfigDict(extra="forbid")

    metric: Literal["visits", "signups", "training_points"]
    bucket: Literal["week", "month", "year"]
    items: list[TimeseriesPoint]


class TopGatewayItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gateway_code: str
    name: str | None
    training_count: int


class TopGatewayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TopGatewayItem]


# ── Gateway moderation (mig 0029) ───────────────────────────────────────


class PendingGatewayResponse(BaseModel):
    """1 gateway chờ admin duyệt (geo.gateway_quarantine row pending_review)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    name: str
    latitude: float
    longitude: float
    altitude_m: float
    frequency_mhz: float
    source_type: str
    contributor_user_id: UUID | None
    contributor_email: str | None
    linked_source_id: UUID | None
    created_at: datetime
    updated_at: datetime


class PendingGatewayListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PendingGatewayResponse]
    total: int = Field(..., ge=0)
