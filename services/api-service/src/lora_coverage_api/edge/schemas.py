"""Pydantic v2 request/response schemas.

KHÔNG expose ORM models. Schema riêng cho edge layer (theo
rule-design-restfulapi.md §6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
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
    bottleneck: Literal["uplink", "downlink", "both_ok"]
    # Path loss tổng (basic transmission loss + BEL nếu có); UL/DL đối xứng.
    path_loss_db: float = 0.0
    # Khoảng cách haversine target → serving gateway (km). 0.0 = no serving GW.
    distance_to_serving_gateway_km: float = 0.0


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
    rx_antenna_gain_dbi: float | None = None
    rx_sensitivity_dbm: float | None = None


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


# ── Survey training (read-only) ───────────────────────────────────────────


class SurveyTrainingPointResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float
    longitude: float
    rssi_dbm: float
    snr_db: float
    spreading_factor: int
    serving_gateway_id: UUID | None


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
    """Per-row outcome breakdown sau khi parse + ingest + (optional) promote.

    `parse_rejected_count` = row CSV bị adapter loại (sai schema, RSSI ngoài
    range, gateway_code không tồn tại). `inserted_count` = row thực sự vào
    quarantine. `promoted_count` + `promote_rejected_count` chỉ > 0 khi
    submit_to_community=true; nếu không thì cả 2 = 0.
    """

    model_config = ConfigDict(extra="forbid")

    parsed_count: int = Field(..., ge=0)
    parse_rejected_count: int = Field(..., ge=0)
    parse_rejected_reasons: list[str] = Field(default_factory=list)
    inserted_count: int = Field(..., ge=0)
    promoted_count: int = Field(..., ge=0)
    promote_rejected_count: int = Field(..., ge=0)
    promote_rejected_by_reason: dict[str, int] = Field(default_factory=dict)


class CsvUploadStats(BaseModel):
    """Tổng quan CSV của 1 user — dùng cho card "Tải lên CSV của tôi"."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(..., ge=0, description="Tổng quarantine row source_type=csv_upload")
    pending: int = Field(
        ...,
        ge=0,
        description="Row còn pending (chưa promote, chưa reject) — số sẽ chạy validator khi user click Đóng góp",
    )
    promoted: int = Field(..., ge=0, description="Row đã promote sang training")
    rejected: int = Field(..., ge=0, description="Row đã reject (set reject_reason)")


class CsvPromoteResponse(BaseModel):
    """Kết quả 1 lần đóng góp tất cả CSV pending."""

    model_config = ConfigDict(extra="forbid")

    promoted_count: int = Field(..., ge=0)
    promote_rejected_count: int = Field(..., ge=0)
    promote_rejected_by_reason: dict[str, int] = Field(default_factory=dict)


class CsvUploadBatch(BaseModel):
    """1 batch = 1 lần upload CSV. Key = uploaded_at (mỗi transaction NOW()
    đồng nhất). FE dùng `uploaded_at` ISO để gọi DELETE."""

    model_config = ConfigDict(extra="forbid")

    uploaded_at: datetime
    total: int = Field(..., ge=0)
    pending: int = Field(..., ge=0)
    promoted: int = Field(..., ge=0)
    rejected: int = Field(..., ge=0)


class CsvUploadBatchList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CsvUploadBatch] = Field(default_factory=list)


class CsvBatchDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted_count: int = Field(..., ge=0)


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
    """Partial update — chỉ field có giá trị mới được apply.

    Cả 2 field None → 400 (request rỗng). Cho phép set cả 2 field cùng lúc.
    `status` chỉ accept 'active'/'paused' từ API; 'failed' do sync
    orchestrator set nội bộ (Step 7).
    """

    model_config = ConfigDict(extra="forbid")

    contribute_to_community: bool | None = None
    status: Literal["active", "paused"] | None = None


class LinkedSourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_type: str
    label: str
    status: Literal["active", "paused", "failed"]
    contribute_to_community: bool
    contributed_at: datetime | None
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
    active_user_count: int = Field(..., ge=0)
    linked_source_count: int = Field(..., ge=0)
    active_source_count: int = Field(..., ge=0)
    gateway_count: int = Field(..., ge=0)
    measurement_count: int = Field(..., ge=0)
