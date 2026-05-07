"""DataSource ABC + uniform record types.

Plan-auth-v1 §3.2 + §10. General-purpose interface cho mọi external data
source (lpwanmapper, ChirpStack, CSV...). Caller (Sync) chỉ thấy iterator
records — adapter ẩn auth, retry, pagination, mapping JSON bên dưới.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Opaque session bag (token, base url, ...). Adapter quyết structure;
# caller không inspect — chỉ giữ và pass lại vào fetch_*.
ConnectionHandle = Any


@dataclass(frozen=True, slots=True)
class GatewayRecord:
    """Uniform gateway snapshot.

    `external_id` là natural key của 1 gateway theo provider — phải stable
    qua các lần fetch của cùng tài khoản, dùng làm dedup key giữa contributors.
    """

    external_id: str
    latitude: float
    longitude: float
    altitude_m: float | None
    label: str | None


@dataclass(frozen=True, slots=True)
class MeasurementRecord:
    """Uniform measurement record.

    `external_id` là natural key của 1 measurement (KHÔNG phải device) —
    dùng dedup khi sync lặp lại.
    `time` phải tz-aware (UTC khuyến nghị).
    """

    external_id: str
    time: datetime
    latitude: float
    longitude: float
    rssi_dbm: float
    snr_db: float | None
    spreading_factor: int | None
    frequency_mhz: float | None
    device_external_id: str
    serving_gateway_external_id: str | None


class DataSource(ABC):
    """Abstract data source.

    Implementations are responsible for:
      * auth lifecycle (re-auth on expiry, transparent to caller)
      * rate limiting + retry với backoff
      * pagination (caller không thấy pagination tokens)
      * mapping provider JSON → GatewayRecord/MeasurementRecord
      * mapping HTTP/network errors → SourceError subclasses

    Implementations MUST NOT:
      * raise raw HTTP/network/JSON errors
      * expose provider-specific identifiers other than via `external_id`
      * giữ mutable state cross-call (handle là state duy nhất)

    Stateless modulo handle. Multiple instances chạy concurrent với
    different credentials được.
    """

    @abstractmethod
    def connect(self, credentials: Mapping[str, Any]) -> ConnectionHandle:
        """Validate credentials và trả handle cho subsequent fetches.

        Raises:
            SourceAuthFailed: credentials invalid/expired
            SourceUnreachable: network/HTTP failure
        """

    @abstractmethod
    def fetch_gateways(self, handle: ConnectionHandle) -> Iterator[GatewayRecord]:
        """Yield mọi gateway visible với credential này. Order unspecified.

        Iterator lazy — caller có thể abort. Adapter chunk via pagination
        nội bộ.

        Raises:
            SourceAuthFailed: token invalid (sau khi auto re-auth thất bại)
            SourceUnreachable: network failure không retry được
            SourceFetchFailed: response invalid (schema/parse error)
        """

    @abstractmethod
    def fetch_measurements(
        self,
        handle: ConnectionHandle,
        since: datetime | None,
    ) -> Iterator[MeasurementRecord]:
        """Yield measurements với time > since. None = fetch all.

        Order: ascending time within same device, ngược lại không xác định.
        Caller dedup theo external_id.

        Raises: same as fetch_gateways.
        """
