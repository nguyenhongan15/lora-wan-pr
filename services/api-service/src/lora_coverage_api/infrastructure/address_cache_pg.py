"""Postgres-backed AddressCache (tier 1 trong cascade).

Lưu vào address.canonical (xem migration 0004). UNIQUE(normalized_query).
Idempotent put — ON CONFLICT DO NOTHING (lần geocode đầu tiên thắng).
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from ..domain.address import AddressLookupResult, GeocodingProvider


class PgAddressCache:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, normalized_query: str) -> AddressLookupResult | None:
        if not normalized_query:
            return None
        sql = text(
            """
            SELECT
                ST_Y(location::geometry) AS lat,
                ST_X(location::geometry) AS lon,
                display_name,
                provider,
                confidence
            FROM address.canonical
            WHERE normalized_query = :q
            """
        )
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"q": normalized_query}).mappings().first()
        if row is None:
            return None
        try:
            provider = GeocodingProvider(row["provider"])
        except ValueError:
            # Provider trong DB không enum-known (legacy/future tier) — quy về NOMINATIM.
            provider = GeocodingProvider.NOMINATIM
        return AddressLookupResult(
            latitude=float(row["lat"]),
            longitude=float(row["lon"]),
            display_name=row["display_name"],
            provider=provider,
            confidence=float(row["confidence"]),
        )

    def put(self, normalized_query: str, hit: AddressLookupResult) -> None:
        if not normalized_query:
            return
        sql = text(
            """
            INSERT INTO address.canonical (
                normalized_query, location, display_name, provider, confidence
            ) VALUES (
                :q,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :display_name, :provider, :confidence
            )
            ON CONFLICT (normalized_query) DO NOTHING
            """
        )
        with self._engine.begin() as conn:
            conn.execute(
                sql,
                {
                    "q": normalized_query,
                    "lat": hit.latitude,
                    "lon": hit.longitude,
                    "display_name": hit.display_name,
                    "provider": hit.provider.value,
                    "confidence": hit.confidence,
                },
            )
