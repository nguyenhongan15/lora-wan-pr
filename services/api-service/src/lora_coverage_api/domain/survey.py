"""Survey domain types — readings từ field uploads.

Pure types + invariants. Theo system-architecture.md §4.2.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
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

# Bounding box Vietnam (lat_min, lat_max, lng_min, lng_max). Dùng cho hard
# gate L1 của TrustValidator: measurement đóng góp cộng đồng phải nằm trong
# VN (Scope Vietnam only). Personal-upload không bắt buộc — caller (validator)
# tự áp dụng theo context.
VIETNAM_LAT_MIN = 8.18
VIETNAM_LAT_MAX = 23.39
VIETNAM_LNG_MIN = 102.14
VIETNAM_LNG_MAX = 109.47


def is_in_vietnam(latitude: float, longitude: float) -> bool:
    """True nếu (lat, lng) nằm trong bbox Vietnam. Helper cho L1 hard gate."""
    return (
        VIETNAM_LAT_MIN <= latitude <= VIETNAM_LAT_MAX
        and VIETNAM_LNG_MIN <= longitude <= VIETNAM_LNG_MAX
    )


# Khoảng cách tối đa từ điểm đo tới serving gateway (km). Trùng filter
# d<50km Stage 1 ETL — survey corruption memory note 2026-05-27 (Hải Phòng
# row gắn gw Đà Nẵng ~554km). Reject ở ingest time → quarantine không
# nhận data invalid ngay từ đầu.
MAX_GATEWAY_DISTANCE_KM = 50.0

_EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance giữa 2 điểm WGS84 (km). Đủ chính xác cho gate
    50km — sai số ellipsoid vs sphere <0.5%."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class SurveyBatchStatus(StrEnum):
    QUARANTINED = "quarantined"  # Đã nhận, chờ validate
    REJECTED = "rejected"  # Schema invalid (whole batch)


@dataclass(frozen=True, slots=True)
class SurveyRecord:
    """1 reading từ thiết bị field. Toạ độ WGS84.

    `submitted_for_community`: caller-driven flag. Mọi ingest path (CSV/JSON
    upload, sync, ChirpStack webhook) đẩy false; user submit batch riêng
    qua `POST /me/uploads/batches/{id}/submit` để flip true. True → record
    chạy qua TrustValidator pipeline; pass → promote sang ts.survey_training.
    False → ở quarantine, chỉ user owner xem được (personal-only).
    """

    timestamp: datetime
    latitude: float
    longitude: float
    rssi_dbm: float
    snr_db: float
    spreading_factor: int
    frequency_mhz: float = 923.0
    device_id: str | None = None
    serving_gateway_id: GatewayId | None = None
    submitted_for_community: bool = False
    code_rate: str | None = None

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError(f"latitude out of range: {self.latitude}")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude out of range: {self.longitude}")
        if not RSSI_MIN_DBM <= self.rssi_dbm <= RSSI_MAX_DBM:
            raise ValueError(f"rssi_dbm {self.rssi_dbm} ngoài [{RSSI_MIN_DBM}, {RSSI_MAX_DBM}]")
        if not SNR_MIN_DB <= self.snr_db <= SNR_MAX_DB:
            raise ValueError(f"snr_db {self.snr_db} ngoài [{SNR_MIN_DB}, {SNR_MAX_DB}]")
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
