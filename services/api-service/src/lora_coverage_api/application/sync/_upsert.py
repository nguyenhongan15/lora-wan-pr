"""Idempotent upsert primitives cho external-source records.

Hai function:
  * upsert_gateway       → geo.gateways (key: source_type, external_id)
  * upsert_measurement   → ts.survey_quarantine
                           (key: timestamp, source_type, external_id)

Caller (sync orchestrator hoặc CLI) quản lý transaction. Mỗi function chạy 1
SQL với ON CONFLICT; trả `UpsertResult` tag tag "inserted"/"updated"/"skipped"
qua trick `RETURNING (xmax = 0)`.

Quyết định:
  * Gateway DO UPDATE: location/altitude có thể đổi nếu user move physical
    gateway. Provenance fields chỉ overwrite khi caller pass non-NULL
    (`COALESCE(EXCLUDED.x, table.x)`).
  * Measurement DO UPDATE: chỉ provenance fields. Payload (rssi/snr/sf...) là
    immutable observation — không bao giờ update.
  * `code` (NOT NULL UNIQUE) = canonical identity của gateway hardware (EUI).
    Cùng 1 physical gateway có thể visible qua nhiều source (vd lpwanmapper
    + chirpstack cùng "thấy" 1 gateway DNIIT). Để tránh `gateways_code_key`
    violation khi user khác link source khác cho cùng hardware, ON CONFLICT
    target = (code). First-writer-wins giữ nguyên source_type/external_id
    của row gốc; provenance fields COALESCE để legacy NULL được tag dần.
  * `frequency_mhz` default 923.0 (AS923-2 ĐN) khi adapter không trả; check
    constraint `chk_freq_lora_band` chỉ cho 433/868/915/923 nên caller phải
    pass giá trị hợp lệ.
  * Target routing (plan community-data-contribution §3.4): measurement
    LUÔN ghi quarantine với cờ `submitted_for_community` set theo
    `linked_sources.contribute_to_community`. Trust pipeline (xem
    application/trust/promotion.py) chịu trách nhiệm copy sang training sau
    khi pass 3 lớp validation — KHÔNG còn path ghi thẳng training.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import Connection, text

from ..sources import DeviceRecord, GatewayRecord, MeasurementRecord

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
    -- Conflict target = code (EUI). Cùng hardware visible qua nhiều source
    -- vẫn ON CONFLICT chính xác — xem module docstring.
    ON CONFLICT (code) DO UPDATE SET
        location            = EXCLUDED.location,
        altitude_m          = EXCLUDED.altitude_m,
        -- Cho phép sync sau "nâng cấp" name khi row cũ vẫn là placeholder
        -- (= code). Adapter set name=code khi source không trả friendly name
        -- (xem upsert_gateway: "name": rec.label or rec.external_id). Khi
        -- source khác về sau có tên thật → cập nhật. Khi user đã có tên thật
        -- rồi → giữ, tránh swing nếu source xoá tên.
        name                = CASE
            WHEN geo.gateways.name = geo.gateways.code THEN EXCLUDED.name
            ELSE geo.gateways.name
        END,
        -- First-writer-wins (plan-auth §3.3 fix): existing trước EXCLUDED →
        -- giữ contributor đầu tiên, không cho user link sau ghi đè data
        -- của user link trước. NULL legacy → fall back EXCLUDED tag dần.
        contributor_user_id = COALESCE(geo.gateways.contributor_user_id, EXCLUDED.contributor_user_id),
        linked_source_id    = COALESCE(geo.gateways.linked_source_id,    EXCLUDED.linked_source_id),
        -- source_type / external_id: cũng first-writer-wins. NULL legacy
        -- (gateway có code nhưng chưa tag source) → fall back EXCLUDED.
        source_type         = COALESCE(geo.gateways.source_type,         EXCLUDED.source_type),
        external_id         = COALESCE(geo.gateways.external_id,         EXCLUDED.external_id),
        updated_at          = now()
    RETURNING (xmax = 0) AS inserted, id
""")


_QUARANTINE_UPSERT_SQL = text("""
    INSERT INTO ts.survey_quarantine (
        timestamp, location, rssi_dbm, snr_db,
        spreading_factor, frequency_mhz, device_id,
        serving_gateway_id, uploader_id,
        external_id, source_type, contributor_user_id, linked_source_id,
        submitted_for_community, code_rate
    )
    VALUES (
        :ts,
        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
        :rssi, :snr, :sf, :freq, :device_id,
        :gw_id, :uploader_id,
        :external_id, :source_type, :contributor_user_id, :linked_source_id,
        :submitted_for_community, :code_rate
    )
    ON CONFLICT (timestamp, source_type, external_id) WHERE external_id IS NOT NULL
    DO UPDATE SET
        -- First-writer-wins: xem comment trong _GATEWAY_UPSERT_SQL.
        contributor_user_id = COALESCE(ts.survey_quarantine.contributor_user_id, EXCLUDED.contributor_user_id),
        linked_source_id    = COALESCE(ts.survey_quarantine.linked_source_id,    EXCLUDED.linked_source_id),
        -- Cờ contribute promoted (false → true) khi user opt-in giữa hai
        -- lần sync — GREATEST giữ true nếu một trong hai bên đã true,
        -- không bao giờ revert true→false (consistency với plan §3.4:
        -- opt-out không xoá data đã đẩy lên cộng đồng).
        submitted_for_community = GREATEST(
            ts.survey_quarantine.submitted_for_community::int,
            EXCLUDED.submitted_for_community::int
        )::boolean
    RETURNING (xmax = 0) AS inserted, id
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


_DEVICE_UPSERT_SQL = text("""
    INSERT INTO geo.devices (
        dev_eui, name, source_type, external_id,
        linked_source_id, contributor_user_id, last_seen_at
    )
    VALUES (
        :dev_eui, :name, :source_type, :external_id,
        :linked_source_id, :contributor_user_id, :last_seen_at
    )
    ON CONFLICT (source_type, external_id) DO UPDATE SET
        name             = COALESCE(EXCLUDED.name, geo.devices.name),
        -- last_seen_at chỉ tiến: GREATEST tránh ghi đè timestamp cũ nếu
        -- provider tạm thời trả NULL hoặc timestamp đi lùi.
        last_seen_at     = GREATEST(geo.devices.last_seen_at, EXCLUDED.last_seen_at),
        linked_source_id = COALESCE(geo.devices.linked_source_id, EXCLUDED.linked_source_id),
        contributor_user_id = COALESCE(geo.devices.contributor_user_id, EXCLUDED.contributor_user_id),
        updated_at       = now()
    RETURNING (xmax = 0) AS inserted
""")


def upsert_device(
    conn: Connection,
    rec: DeviceRecord,
    *,
    source_type: str,
    linked_source_id: UUID | None,
    contributor_user_id: UUID | None,
) -> UpsertResult:
    """Insert hoặc update 1 device row. KHÔNG raise — caller wrap transaction.

    geo.devices KHÔNG phải dependency của ingest path; chỉ là projection
    cho FE list. Update conflict overwrite metadata (name) + advance
    last_seen_at; giữ contributor cũ (first-writer-wins) — user khác link
    cùng deployment ChirpStack (cùng tenant) không "cướp" device.
    """
    row = conn.execute(
        _DEVICE_UPSERT_SQL,
        {
            "dev_eui": rec.dev_eui,
            "name": rec.name,
            "source_type": source_type,
            "external_id": rec.external_id,
            "linked_source_id": linked_source_id,
            "contributor_user_id": contributor_user_id,
            "last_seen_at": rec.last_seen_at,
        },
    ).one()
    return "inserted" if row.inserted else "updated"


def upsert_measurement(
    conn: Connection,
    rec: MeasurementRecord,
    *,
    source_type: str,
    serving_gateway_id: UUID | None,
    uploader_id: UUID,
    contributor_user_id: UUID | None = None,
    linked_source_id: UUID | None = None,
    submitted_for_community: bool = False,
) -> UpsertResult:
    """Insert hoặc update provenance của 1 measurement trong ts.survey_quarantine.

    `serving_gateway_id` (UUID PK của geo.gateways) caller resolve trước qua
    map external_id → uuid (build từ output của upsert_gateway).

    `submitted_for_community` (plan community-data-contribution §3.4):
      * False — personal-only, mãi mãi ở quarantine (chỉ user owner xem được).
      * True  — đủ điều kiện chạy qua TrustValidator pipeline; pass → promote
        sang training. Sync orchestrator pass theo `linked_sources.
        contribute_to_community`; CSV upload pass theo checkbox của user.
    """
    freq = rec.frequency_mhz if rec.frequency_mhz is not None else DEFAULT_FREQUENCY_MHZ

    row = conn.execute(
        _QUARANTINE_UPSERT_SQL,
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
            "submitted_for_community": submitted_for_community,
            "code_rate": rec.code_rate,
        },
    ).one()
    return "inserted" if row.inserted else "updated"
