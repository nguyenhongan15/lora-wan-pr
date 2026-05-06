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
from typing import Protocol
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
    ) -> Sequence[Gateway]:
        """List gateways, optional filter theo bbox (min_lon, min_lat, max_lon, max_lat)."""
        ...

    def get_by_id(self, gateway_id: GatewayId) -> Gateway | None:
        ...

    def create(self, gateway: Gateway) -> Gateway:
        """Insert mới. Trả gateway đã có id từ DB."""
        ...

    def update(self, gateway_id: GatewayId, patch: dict[str, object]) -> Gateway | None:
        """Partial update. Trả Gateway sau khi update, hoặc None nếu không tồn tại."""
        ...


class CoverageQuery(Protocol):
    def predict(self, target: Target) -> Result[Prediction, PredictionUnavailable]:
        ...


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
        self, batch: SurveyBatch, record_ids: Sequence[UUID]
    ) -> int:
        """Như `write_quarantine` nhưng ID do caller cung cấp + ON CONFLICT
        DO NOTHING ở (timestamp, id).

        Dùng cho ChirpStack webhook (network server có thể retry cùng uplink
        khi mất ack). `record_ids` PHẢI cùng độ dài với `batch.records`.

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
        bbox: tuple[float, float, float, float] | None = None,
        limit: int = 1000,
        device_id: str | None = None,
    ) -> Sequence[TrainingPoint]:
        """List promoted survey points cho map visualization."""
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

    def get(self, normalized_query: str) -> AddressLookupResult | None:
        ...

    def put(self, normalized_query: str, hit: AddressLookupResult) -> None:
        """Idempotent upsert. KHÔNG raise nếu key đã tồn tại."""
        ...
