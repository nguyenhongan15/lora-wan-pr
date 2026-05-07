"""In-memory DataSource fake.

Test sync orchestrator + registry mà không cần HTTP. Inject records qua
constructor; iterator yield theo thứ tự cung cấp.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any

from lora_coverage_api.application.sources import (
    DataSource,
    GatewayRecord,
    MeasurementRecord,
    SourceAuthFailed,
)


class FakeDataSource(DataSource):
    """Adapter giả lập. `connect()` accept bất cứ credentials nào trừ rỗng.

    `gateways` và `measurements` inject qua constructor. `since` filter
    áp dụng nếu có.
    """

    def __init__(
        self,
        gateways: list[GatewayRecord] | None = None,
        measurements: list[MeasurementRecord] | None = None,
    ) -> None:
        self._gateways = gateways or []
        self._measurements = measurements or []
        self.connect_calls = 0

    def connect(self, credentials: Mapping[str, Any]) -> dict:
        self.connect_calls += 1
        if not credentials:
            raise SourceAuthFailed("empty credentials")
        return {"token": "fake-token"}

    def fetch_gateways(self, handle: Any) -> Iterator[GatewayRecord]:
        yield from self._gateways

    def fetch_measurements(
        self,
        handle: Any,
        since: datetime | None,
    ) -> Iterator[MeasurementRecord]:
        for m in self._measurements:
            if since is None or m.time > since:
                yield m
