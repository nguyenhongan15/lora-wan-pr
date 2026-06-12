"""ChirpStack webhook ingest use case.

Đứng ở application layer vì điều phối: adapter (pure) + repo (idempotent).
Edge router chỉ gọi service này; KHÔNG biết cấu trúc ChirpStack.

Idempotency: ChirpStack network server retry khi mất ack. Chúng ta dùng
deterministic UUID derived từ deduplicationId + rx_index → cùng uplink retry
luôn cho ra cùng record_id → DB-level ON CONFLICT DO NOTHING xử lý hết.

Provenance (plan ChirpStack per-user webhook ingest §4): WebhookContext
do edge resolver tạo ra chứa uploader_id + linked_source_id + source_type.
Adapter ép từng row mang đủ provenance để filter "my data" + "community
public" hoạt động cùng pattern với sync REST.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from ..domain.survey import (
    MAX_GATEWAY_DISTANCE_KM,
    SurveyBatch,
    UploaderId,
    haversine_km,
)
from .chirpstack_adapter import (
    AdapterResult,
    chirpstack_uplink_to_survey_records,
)
from .repositories import SurveyIngest
from .webhook_auth import WebhookContext

# ChirpStack adapter là source_type duy nhất ingest qua webhook hiện tại.
# Đẩy lên const để khi expose webhook cho source khác (vd LoRaWAN gateway
# bridge), chỗ này dễ override.
_WEBHOOK_SOURCE_TYPE = "chirpstack"

# Namespace cố định để uuid5 deterministic giữa các lần restart.
# UUID này KHÔNG bí mật, nó chỉ là salt cho hash đầu vào.
_DEDUP_NS = uuid.UUID("9c5b2d3e-1f08-4f2c-9e80-bda9c1e5a401")


@dataclass(frozen=True, slots=True)
class WebhookIngestReceipt:
    """Trả về cho ChirpStack network server (đặt trong response 202)."""

    accepted_count: int  # số record adapter coi là hợp lệ
    inserted_count: int  # số record THỰC SỰ insert (sau dedup)
    rejected_count: int  # số rxInfo bị adapter loại
    rejected_reasons: list[str]


def _external_id(deduplication_id: str, rx_index: int) -> str:
    """Natural key text cho 1 (uplink, rxInfo[i]) — lưu vào `external_id`.

    Cùng deduplication_id + cùng rx_index → cùng external_id; UNIQUE PARTIAL
    `(timestamp, source_type, external_id)` chặn dup nếu cùng uplink replay
    qua route khác.
    """
    return f"{deduplication_id}:{rx_index}"


def _record_id(deduplication_id: str, rx_index: int) -> uuid.UUID:
    """Derive deterministic UUID cho 1 (uplink, rxInfo[i]).

    Cùng deduplicationId + cùng rx_index → luôn cùng UUID → idempotent.
    """
    return uuid.uuid5(_DEDUP_NS, _external_id(deduplication_id, rx_index))


class ChirpstackWebhookService:
    def __init__(self, repository: SurveyIngest) -> None:
        self._repo = repository

    def ingest_uplink(
        self,
        uplink: dict[str, Any],
        context: WebhookContext,
    ) -> WebhookIngestReceipt:
        """Adapter → deterministic ids → idempotent write với full provenance.

        `context` đã do `WebhookAuthService.resolve()` validate ở edge — service
        layer trust nó. uploader_id = contributor_user_id (cùng user là người
        push qua webhook và sở hữu data); linked_source_id + source_type
        đẩy thẳng xuống repo để filter contributor hoạt động.
        """
        adapter_result: AdapterResult = chirpstack_uplink_to_survey_records(uplink)
        rejected = list(adapter_result.rejected)

        if not adapter_result.records:
            return WebhookIngestReceipt(
                accepted_count=0,
                inserted_count=0,
                rejected_count=len(rejected),
                rejected_reasons=rejected,
            )

        # Filter distance gateway → measurement (>50km). Adapter đã reject
        # bbox; ở đây chỉ cần distance check. Records không match gateway
        # external_id trong DB → giữ lại (không thể check, fall through theo
        # behavior hiện tại — serving_gateway_id=None ở quarantine).
        gw_ext_ids = adapter_result.gateway_external_ids
        unique_ext = {x for x in gw_ext_ids if x}
        coords_map = (
            self._repo.lookup_gateway_coords(
                source_type=_WEBHOOK_SOURCE_TYPE,
                external_ids=list(unique_ext),
            )
            if unique_ext
            else {}
        )

        kept_records = []
        kept_orig_idx: list[int] = []
        for orig_i, (rec, gw_ext) in enumerate(
            zip(adapter_result.records, gw_ext_ids, strict=True)
        ):
            if gw_ext and gw_ext in coords_map:
                gw_lat, gw_lon = coords_map[gw_ext]
                dist_km = haversine_km(rec.latitude, rec.longitude, gw_lat, gw_lon)
                if dist_km > MAX_GATEWAY_DISTANCE_KM:
                    rejected.append(
                        f"gateway distance {dist_km:.1f}km > {MAX_GATEWAY_DISTANCE_KM}km"
                    )
                    continue
            kept_records.append(rec)
            kept_orig_idx.append(orig_i)

        if not kept_records:
            return WebhookIngestReceipt(
                accepted_count=0,
                inserted_count=0,
                rejected_count=len(rejected),
                rejected_reasons=rejected,
            )

        dedup_id = uplink.get("deduplicationId") or uplink.get("_id") or ""
        ids: list[uuid.UUID]
        external_ids: list[str | None]
        if not isinstance(dedup_id, str) or not dedup_id:
            # Không có dedup → fallback random uuid (mất idempotency).
            ids = [uuid.uuid4() for _ in kept_records]
            external_ids = [None] * len(kept_records)
        else:
            # rx_index = index GỐC trong rxInfo (trước filter) → cùng uplink
            # retry → cùng external_id bất kể distance filter output.
            ids = [_record_id(dedup_id, i) for i in kept_orig_idx]
            external_ids = [_external_id(dedup_id, i) for i in kept_orig_idx]

        batch = SurveyBatch(
            uploader_id=UploaderId(context.user_id),
            records=kept_records,
        )
        inserted = self._repo.write_quarantine_idempotent(
            batch,
            ids,
            external_ids=external_ids,
            source_type=context.source_type,
            linked_source_id=context.linked_source_id,
            contributor_user_id=context.user_id,
            submitted_for_community=False,
        )

        return WebhookIngestReceipt(
            accepted_count=len(kept_records),
            inserted_count=inserted,
            rejected_count=len(rejected),
            rejected_reasons=rejected,
        )
