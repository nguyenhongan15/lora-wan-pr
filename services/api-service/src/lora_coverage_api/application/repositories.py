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

from ..domain.coverage import Gateway, GatewayId, Prediction, Target
from ..domain.errors import PredictionUnavailable
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
        """Insert toàn bộ records vào ts.survey_quarantine. Trả batch_id."""
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
