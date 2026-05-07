"""Idempotent upsert primitives cho external-source records.

Hai function:
  * upsert_gateway       → geo.gateways (key: source_type, external_id)
  * upsert_measurement   → ts.survey_quarantine (key: timestamp, source_type, external_id)

Caller (sync orchestrator hoặc CLI) quản lý transaction. Mỗi function chạy 1
SQL với ON CONFLICT; trả `UpsertResult` tag tag "inserted"/"updated"/"skipped"
qua trick `RETURNING (xmax = 0)`.

Quyết định:
  * Gateway DO UPDATE: location/altitude có thể đổi nếu user move physical
    gateway. Provenance fields chỉ overwrite khi caller pass non-NULL
    (`COALESCE(EXCLUDED.x, table.x)`).
  * Measurement DO UPDATE: chỉ provenance fields. Payload (rssi/snr/sf...) là
    immutable observation — không bao giờ update.
  * `code` (NOT NULL UNIQUE legacy column) = `external_id` cho lpwanmapper. Sau
    backfill_provenance, legacy rows cũng follow convention này, nên ON CONFLICT
    (source_type, external_id) khớp đúng row → không trigger
    `gateways_code_key` violation.
  * `frequency_mhz` default 923.0 (AS923-2 ĐN) khi adapter không trả; check
    constraint `chk_freq_lora_band` chỉ cho 433/868/915/923 nên caller phải
    pass giá trị hợp lệ.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import Connection, text

from ..sources import GatewayRecord, MeasurementRecord

UpsertResult = Literal["inserted", "updated"]

DEFAULT_FREQUENCY_MHZ = 923.0  # AS923-2 (Đà Nẵng / VN)
_ALLOWED_FREQ_MHZ = (433.0, 868.0, 915.0, 923.0)


_GATEWAY_UPSERT_SQL = text("""
    INSERT INTO geo.gateways (
        code, name, location, altitude_m, frequency_mhz,
        external_id, source_type, contributor_user_id, linked_source_id
    )
    VALUES (
        :code, :name,
        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
        :altitude_m, :freq_mhz,
        :external_id, :source_type, :contributor_user_id, :linked_source_id
    )
    ON CONFLICT (source_type, external_id) WHERE external_id IS NOT NULL
    DO UPDATE SET
        location            = EXCLUDED.location,
        altitude_m          = EXCLUDED.altitude_m,
        contributor_user_id = COALESCE(EXCLUDED.contributor_user_id, geo.gateways.contributor_user_id),
        linked_source_id    = COALESCE(EXCLUDED.linked_source_id,    geo.gateways.linked_source_id),
        updated_at          = now()
    RETURNING (xmax = 0) AS inserted, id
""")


_MEASUREMENT_UPSERT_SQL = text("""
    INSERT INTO ts.survey_quarantine (
        timestamp, location, rssi_dbm, snr_db,
        spreading_factor, frequency_mhz, device_id,
        serving_gateway_id, uploader_id,
        external_id, source_type, contributor_user_id, linked_source_id
    )
    VALUES (
        :ts,
        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
        :rssi, :snr, :sf, :freq, :device_id,
        :gw_id, :uploader_id,
        :external_id, :source_type, :contributor_user_id, :linked_source_id
    )
    ON CONFLICT (timestamp, source_type, external_id) WHERE external_id IS NOT NULL
    DO UPDATE SET
        contributor_user_id = COALESCE(EXCLUDED.contributor_user_id, ts.survey_quarantine.contributor_user_id),
        linked_source_id    = COALESCE(EXCLUDED.linked_source_id,    ts.survey_quarantine.linked_source_id)
    RETURNING (xmax = 0) AS inserted
""")


def upsert_gateway(
    conn: Connection,
    rec: GatewayRecord,
    *,
    source_type: str,
    contributor_user_id: UUID | None = None,
    linked_source_id: UUID | None = None,
    frequency_mhz: float = DEFAULT_FREQUENCY_MHZ,
) -> tuple[UpsertResult, UUID]:
    """Insert hoặc update 1 gateway. Trả (status, gateway_uuid).

    `gateway_uuid` luôn được resolve (cả insert mới lẫn match existing) để
    caller dùng làm FK cho measurements ngay sau đó.
    """
    if frequency_mhz not in _ALLOWED_FREQ_MHZ:
        raise ValueError(
            f"frequency_mhz={frequency_mhz} không thuộc band cho phép {_ALLOWED_FREQ_MHZ}"
        )

    row = conn.execute(
        _GATEWAY_UPSERT_SQL,
        {
            "code": rec.external_id,
            "name": rec.label or rec.external_id,
            "lat": rec.latitude,
            "lon": rec.longitude,
            "altitude_m": rec.altitude_m if rec.altitude_m is not None else 0.0,
            "freq_mhz": frequency_mhz,
            "external_id": rec.external_id,
            "source_type": source_type,
            "contributor_user_id": contributor_user_id,
            "linked_source_id": linked_source_id,
        },
    ).one()
    return ("inserted" if row.inserted else "updated", row.id)


def upsert_measurement(
    conn: Connection,
    rec: MeasurementRecord,
    *,
    source_type: str,
    serving_gateway_id: UUID | None,
    uploader_id: UUID,
    contributor_user_id: UUID | None = None,
    linked_source_id: UUID | None = None,
) -> UpsertResult:
    """Insert hoặc update provenance của 1 measurement.

    `serving_gateway_id` (UUID PK của geo.gateways) caller resolve trước qua
    map external_id → uuid (build từ output của upsert_gateway).
    """
    freq = rec.frequency_mhz if rec.frequency_mhz is not None else DEFAULT_FREQUENCY_MHZ

    row = conn.execute(
        _MEASUREMENT_UPSERT_SQL,
        {
            "ts": rec.time,
            "lat": rec.latitude,
            "lon": rec.longitude,
            "rssi": rec.rssi_dbm,
            "snr": rec.snr_db if rec.snr_db is not None else 0.0,
            "sf": rec.spreading_factor if rec.spreading_factor is not None else 7,
            "freq": freq,
            "device_id": rec.device_external_id,
            "gw_id": serving_gateway_id,
            "uploader_id": uploader_id,
            "external_id": rec.external_id,
            "source_type": source_type,
            "contributor_user_id": contributor_user_id,
            "linked_source_id": linked_source_id,
        },
    ).one()
    return "inserted" if row.inserted else "updated"
