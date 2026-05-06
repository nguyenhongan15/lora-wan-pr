"""In-memory GatewayDirectory fake.

Honors GatewayDirectory Protocol. Tests assert qua observable behavior
(`find_serving_candidates` trả gì), không introspection internals.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from lora_coverage_api.domain.coverage import Gateway, GatewayId, Target


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class FakeGatewayDirectory:
    """In-memory GatewayDirectory. Seed bằng list[Gateway] hoặc dùng add()."""

    def __init__(self, gateways: Sequence[Gateway] = ()) -> None:
        self._store: dict[GatewayId, Gateway] = {gw.id: gw for gw in gateways}

    def add(self, gateway: Gateway) -> None:
        self._store[gateway.id] = gateway

    def find_serving_candidates(
        self, target: Target, max_distance_km: float = 30.0, limit: int = 5
    ) -> Sequence[Gateway]:
        scored = [
            (
                _haversine_km(target.latitude, target.longitude, gw.latitude, gw.longitude),
                gw,
            )
            for gw in self._store.values()
        ]
        in_range = [(d, gw) for d, gw in scored if d <= max_distance_km]
        in_range.sort(key=lambda t: t[0])
        return [gw for _, gw in in_range[:limit]]

    def list_gateways(
        self,
        bbox: tuple[float, float, float, float] | None = None,
        is_public: bool | None = True,
        limit: int = 500,
    ) -> Sequence[Gateway]:
        items = list(self._store.values())
        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            items = [
                gw
                for gw in items
                if min_lon <= gw.longitude <= max_lon and min_lat <= gw.latitude <= max_lat
            ]
        return items[:limit]

    def get_by_id(self, gateway_id: GatewayId) -> Gateway | None:
        return self._store.get(gateway_id)

    def create(self, gateway: Gateway) -> Gateway:
        self._store[gateway.id] = gateway
        return gateway

    def update(self, gateway_id: GatewayId, patch: dict[str, object]) -> Gateway | None:
        existing = self._store.get(gateway_id)
        if existing is None:
            return None
        from dataclasses import replace

        updated = replace(existing, **patch)  # type: ignore[arg-type]
        self._store[gateway_id] = updated
        return updated
