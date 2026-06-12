"""Repository protocols (capability interfaces).

Theo data-architecture.md §3 — 4 capability:
  - CoverageQuery
  - SurveyIngest
  - GatewayDirectory
  - AddressResolution

v2 implement: CoverageQuery, GatewayDirectory (full CRUD), SurveyIngest.
AddressResolution vẫn defer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from ..domain.address import Address, AddressLookupResult
from ..domain.coverage import Gateway, GatewayId, Prediction, Target
from ..domain.errors import AddressLookupError, PredictionUnavailable
from ..domain.result import Result
from ..domain.survey import SurveyBatch, SurveyBatchId


class GatewayDirectory(Protocol):
    """Read-side cho prediction (find candidates) + CRUD admin."""

    def find_serving_candidates(
        self, target: Target, max_distance_km: float = 30.0, limit: int = 5
    ) -> Sequence[Gateway]:
        """Trả các gateway gần nhất, đã sort theo khoảng cách tăng dần."""
        ...

    def list_gateways(
        self,
        bbox: tuple[float, float, float, float] | None = None,
        is_public: bool | None = True,
        limit: int = 500,
        contributor: ContributorSpec | None = None,
    ) -> Sequence[Gateway]:
        """List gateways, optional filter theo bbox (min_lon, min_lat, max_lon, max_lat).

        Khi `contributor.mode` ∈ {self, user}: chỉ trả gateway từng phục vụ
        ít nhất 1 survey training point của user đó (JOIN ts.survey_training
        trên `serving_gateway_id`). Mode `community` hoặc None: behavior cũ
        (tất cả gateway match bbox/is_public).
        """
        ...

    def get_by_id(self, gateway_id: GatewayId) -> Gateway | None: ...

    def get_by_code(self, code: str) -> Gateway | None:
        """Lookup by business code (vd 'DAD-012'). Dùng cho CSV upload —
        user nhập gateway code thay vì UUID. Trả None nếu không tồn tại.
        """
        ...

    def create(self, gateway: Gateway) -> Gateway:
        """Insert mới. Trả gateway đã có id từ DB."""
        ...

    def update(self, gateway_id: GatewayId, patch: dict[str, object]) -> Gateway | None:
        """Partial update. Trả Gateway sau khi update, hoặc None nếu không tồn tại."""
        ...


class CoverageQuery(Protocol):
    def predict(self, target: Target) -> Result[Prediction, PredictionUnavailable]: ...


class SurveyIngest(Protocol):
    """Write-side cho survey uploads.

    v2 chỉ ingest vào quarantine. Promote sang training là async job
    (chưa có worker-service ở v2 → promote thủ công bằng SQL hoặc seed script).
    """

    def write_quarantine(self, batch: SurveyBatch) -> SurveyBatchId:
        """Insert toàn bộ records vào ts.survey_quarantine. Trả batch_id.

        ID record sinh ngẫu nhiên (uuid4) — KHÔNG idempotent.
        """
        ...

    def write_quarantine_idempotent(
        self,
        batch: SurveyBatch,
        record_ids: Sequence[UUID],
        *,
        external_ids: Sequence[str | None] | None = None,
        source_type: str | None = None,
        linked_source_id: UUID | None = None,
        contributor_user_id: UUID | None = None,
        submitted_for_community: bool = False,
        batch_id: UUID | None = None,
    ) -> int:
        """Như `write_quarantine` nhưng ID do caller cung cấp + ON CONFLICT
        DO NOTHING ở (timestamp, id).

        Dùng cho ChirpStack webhook (network server có thể retry cùng uplink
        khi mất ack). `record_ids` PHẢI cùng độ dài với `batch.records`.

        Provenance kwargs (plan ChirpStack webhook step 4):
          * `external_ids` — per-record natural key text (vd "dedup_id:rx_index"
            cho ChirpStack). Cùng độ dài với batch.records nếu set; None ngầm
            mỗi entry None.
          * `source_type` / `linked_source_id` / `contributor_user_id` —
            batch-level provenance, áp dụng cho mọi row trong batch. Webhook
            ingest đọc từ `WebhookContext`; legacy path (chưa migrate) pass
            None để giữ behaviour cũ.
          * `submitted_for_community`: cờ batch-level đẩy xuống cột
            `submitted_for_community`. Mọi ingest path đẩy false; flip true
            khi user submit batch qua `POST /me/uploads/batches/{id}/submit`.
          * `batch_id` (mig 0024) — FK xuống `me.upload_batches`. Caller
            tạo row batch trước rồi pass id xuống đây; None = legacy path
            chưa migrate (vd webhook real-time chưa nối).

        Trả số record THỰC SỰ insert (đã trừ duplicate skip).
        """
        ...

    def list_quarantine(
        self, uploader_id: UUID | None = None, limit: int = 100
    ) -> Sequence[tuple[SurveyBatchId, int]]:
        """List (batch_id, record_count) gần nhất. Dùng cho admin/audit."""
        ...

    def list_training(
        self,
        *,
        contributor: ContributorSpec,
        bbox: tuple[float, float, float, float] | None = None,
        offset: int = 0,
        limit: int = 1000,
        device_id: str | None = None,
        source_type: str | None = None,
        sf_list: Sequence[int] | None = None,
        rssi_min: float | None = None,
        rssi_max: float | None = None,
        snr_min: float | None = None,
        snr_max: float | None = None,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
        since: datetime | None = None,
        sort_by: Literal["timestamp", "rssi", "snr"] = "timestamp",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> Sequence[TrainingPoint]:
        """List promoted survey points cho map visualization.

        `contributor` đã được authorize ở edge — repository chỉ áp dụng
        WHERE clause tương ứng với mode (xem ContributorSpec).

        offset/limit thay cho 1 limit thuần — caller có thể "lấy điểm hạng
        N..M sau khi sort". Edge router map rank_from/rank_to → offset+limit.

        sort_by + sort_order: cho phép chọn trục xếp hạng (timestamp mặc định
        DESC = newest first; rssi DESC = mạnh nhất trước; snr DESC = clean
        nhất trước). Tie-break thêm timestamp DESC để OFFSET deterministic.
        """
        ...

    def lookup_gateway_coords(
        self,
        *,
        source_type: str,
        external_ids: Sequence[str],
    ) -> dict[str, tuple[float, float]]:
        """Bulk lookup gateway (lat, lng) theo (source_type, external_id).

        Webhook ingest dùng để filter measurement có serving gateway > 50km
        khỏi điểm đo TRƯỚC khi insert quarantine. external_id nào không match
        → vắng mặt trong dict (caller tự xử case "không tìm thấy gw" =
        không thể check distance).
        """
        ...

    def list_user_devices(
        self,
        *,
        user_id: UUID,
        linked_source_id: UUID | None = None,
    ) -> Sequence[UserDevice]:
        """List distinct device_id của 1 user trên ts.survey_training, kèm
        số điểm. Optional narrow theo linked_source_id (đã verify ownership
        ở edge nếu cần — repository chỉ AND vào WHERE).

        Sort: count DESC, device_id ASC để UI hiển thị thiết bị nhiều data
        trước.
        """
        ...


@dataclass(frozen=True, slots=True)
class UserDevice:
    """Read-model: 1 device_id của user, kèm số điểm đo. Dùng cho dropdown
    filter "Bản đồ của tôi" → dropdown thiết bị thay vì text input."""

    device_id: str
    count: int


@dataclass(frozen=True, slots=True)
class LinkedSourceDevice:
    """Read-model: 1 device entry trong `geo.devices` (sync REST).

    Khác `UserDevice` (đếm điểm trong survey_training). Field map 1-1 với
    cột DB — edge router projects sang DeviceResponse.
    """

    id: UUID
    dev_eui: str
    name: str | None
    source_type: str
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeviceQuery(Protocol):
    """Read-side cho `geo.devices`. Sync orchestrator owns write path qua
    `application/sync/_upsert.py`; capability này phục vụ FE list devices
    của 1 linked_source mà user đã verify ownership ở edge."""

    def list_by_linked_source(
        self,
        *,
        linked_source_id: UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[LinkedSourceDevice], int]:
        """Trả (items page, total count) cho 1 linked_source.

        Sort: `last_seen_at DESC NULLS LAST, dev_eui ASC` — FE hiển thị
        thiết bị mới hoạt động lên đầu, NULL (chưa từng uplink) xuống cuối.
        Ownership đã được edge verify (linked_source thuộc user); repository
        không re-check.
        """
        ...


@dataclass(frozen=True, slots=True)
class TrainingPoint:
    """Read-model cho map: 1 survey training point đã promoted."""

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


@dataclass(frozen=True, slots=True)
class ContributorSpec:
    """Resolved filter cho `list_training`. Đã được authorize ở edge layer
    (xem edge/filters.py:resolve_contributor) — repository không kiểm tra
    quyền lại, chỉ build SQL.

    `mode`:
        community → public map; chỉ data có submitted_for_community=true (đã
                    qua admin duyệt → training), linked_source.status='active',
                    uploader chưa bị disable.
        self      → data của current_user; bypass filter (user thấy data của
                    mình kể cả khi chưa submit batch).
        user      → admin xem 1 user_id cụ thể; bypass filter.

    `linked_source_id` chỉ có nghĩa khi mode='self' (sub-filter UI). Edge
    resolver đã verify ownership trước khi set field này.
    """

    mode: Literal["community", "self", "user"]
    target_user_id: UUID | None = None
    linked_source_id: UUID | None = None


class AddressResolution(Protocol):
    """F2 funnel — input là chuỗi địa chỉ, output là toạ độ canonical.

    Theo data-architecture.md §3.4. Cascade implementation (Postgres cache →
    Nominatim → VietMap/Goong → Google) sống ở application/address_service.py;
    Protocol này chỉ định nghĩa interface dùng cho coverage lookup endpoint.
    """

    def lookup(self, address: Address) -> Result[AddressLookupResult, AddressLookupError]:
        """Trả toạ độ + display_name canonical, hoặc Err với code rõ ràng."""
        ...


class AddressCache(Protocol):
    """Read/write cho address.canonical (tier 1 trong cascade).

    Tách riêng khỏi `AddressResolution` để các tier khác (Nominatim) chỉ phụ
    thuộc cache, không phụ thuộc cả service.
    """

    def get(self, normalized_query: str) -> AddressLookupResult | None: ...

    def put(self, normalized_query: str, hit: AddressLookupResult) -> None:
        """Idempotent upsert. KHÔNG raise nếu key đã tồn tại."""
        ...
