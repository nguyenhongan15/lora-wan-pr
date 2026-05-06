"""ChirpStack webhook ingest use case.

Đứng ở application layer vì điều phối: adapter (pure) + repo (idempotent).
Edge router chỉ gọi service này; KHÔNG biết cấu trúc ChirpStack.

Idempotency: ChirpStack network server retry khi mất ack. Chúng ta dùng
deterministic UUID derived từ deduplicationId + rx_index → cùng uplink retry
luôn cho ra cùng record_id → DB-level ON CONFLICT DO NOTHING xử lý hết.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from .chirpstack_adapter import (
    AdapterResult,
    chirpstack_uplink_to_survey_records,
)
from .repositories import SurveyIngest
from ..domain.survey import SurveyBatch, UploaderId

# Namespace cố định để uuid5 deterministic giữa các lần restart.
# UUID này KHÔNG bí mật, nó chỉ là salt cho hash đầu vào.
_DEDUP_NS = uuid.UUID("9c5b2d3e-1f08-4f2c-9e80-bda9c1e5a401")


@dataclass(frozen=True, slots=True)
class WebhookIngestReceipt:
    """Trả về cho ChirpStack network server (đặt trong response 202)."""

    accepted_count: int   # số record adapter coi là hợp lệ
    inserted_count: int   # số record THỰC SỰ insert (sau dedup)
    rejected_count: int   # số rxInfo bị adapter loại
    rejected_reasons: list[str]


def _record_id(deduplication_id: str, rx_index: int) -> uuid.UUID:
    """Derive deterministic UUID cho 1 (uplink, rxInfo[i]).

    Cùng deduplicationId + cùng rx_index → luôn cùng UUID → idempotent.
    """
    return uuid.uuid5(_DEDUP_NS, f"{deduplication_id}:{rx_index}")


class ChirpstackWebhookService:
    def __init__(self, repository: SurveyIngest) -> None:
        self._repo = repository

    def ingest_uplink(
        self,
        uplink: dict[str, Any],
        uploader_id: UploaderId,
    ) -> WebhookIngestReceipt:
        """Adapter → deterministic ids → idempotent write."""
        adapter_result: AdapterResult = chirpstack_uplink_to_survey_records(uplink)

        if not adapter_result.records:
            return WebhookIngestReceipt(
                accepted_count=0,
                inserted_count=0,
                rejected_count=len(adapter_result.rejected),
                rejected_reasons=adapter_result.rejected,
            )

        dedup_id = uplink.get("deduplicationId") or uplink.get("_id") or ""
        if not isinstance(dedup_id, str) or not dedup_id:
            # Không có dedup → fallback random uuid (mất idempotency cho uplink này).
            ids = [uuid.uuid4() for _ in adapter_result.records]
        else:
            # rx_index map theo thứ tự records adapter trả ra. Adapter giữ
            # thứ tự rxInfo gốc (đã có test bao phủ).
            ids = [
                _record_id(dedup_id, i)
                for i in range(len(adapter_result.records))
            ]

        batch = SurveyBatch(uploader_id=uploader_id, records=adapter_result.records)
        inserted = self._repo.write_quarantine_idempotent(batch, ids)

        return WebhookIngestReceipt(
            accepted_count=len(adapter_result.records),
            inserted_count=inserted,
            rejected_count=len(adapter_result.rejected),
            rejected_reasons=adapter_result.rejected,
        )
