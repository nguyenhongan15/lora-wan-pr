"""Survey domain types — readings từ field uploads.

Pure types + invariants. Theo system-architecture.md §4.2.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import NewType
from uuid import UUID, uuid4

from .coverage import GatewayId

SurveyBatchId = NewType("SurveyBatchId", UUID)
UploaderId = NewType("UploaderId", UUID)

# Validation ranges (theo §4.2 outlier detection)
RSSI_MIN_DBM = -150.0
RSSI_MAX_DBM = -30.0
SNR_MIN_DB = -30.0
SNR_MAX_DB = 30.0


class SurveyBatchStatus(str, Enum):
    QUARANTINED = "quarantined"  # Đã nhận, chờ validate
    REJECTED = "rejected"        # Schema invalid (whole batch)


@dataclass(frozen=True, slots=True)
class SurveyRecord:
    """1 reading từ thiết bị field. Toạ độ WGS84."""

    timestamp: datetime
    latitude: float
    longitude: float
    rssi_dbm: float
    snr_db: float
    spreading_factor: int
    frequency_mhz: float = 868.0
    device_id: str | None = None
    serving_gateway_id: GatewayId | None = None

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError(f"latitude out of range: {self.latitude}")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude out of range: {self.longitude}")
        if not RSSI_MIN_DBM <= self.rssi_dbm <= RSSI_MAX_DBM:
            raise ValueError(
                f"rssi_dbm {self.rssi_dbm} ngoài [{RSSI_MIN_DBM}, {RSSI_MAX_DBM}]"
            )
        if not SNR_MIN_DB <= self.snr_db <= SNR_MAX_DB:
            raise ValueError(
                f"snr_db {self.snr_db} ngoài [{SNR_MIN_DB}, {SNR_MAX_DB}]"
            )
        if self.spreading_factor not in (7, 8, 9, 10, 11, 12):
            raise ValueError(f"invalid SF: {self.spreading_factor}")


@dataclass(frozen=True, slots=True)
class SurveyBatchReceipt:
    """Acknowledgement trả về client sau upload (202 Accepted)."""

    batch_id: SurveyBatchId
    status: SurveyBatchStatus
    accepted_count: int
    rejected_count: int
    estimated_review_hours: int = 24


@dataclass(frozen=True, slots=True)
class SurveyBatch:
    """Batch nguyên gốc từ uploader. Đã pass schema validation."""

    uploader_id: UploaderId
    records: Sequence[SurveyRecord]
    batch_id: SurveyBatchId = field(default_factory=lambda: SurveyBatchId(uuid4()))
