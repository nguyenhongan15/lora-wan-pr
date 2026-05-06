"""Import survey measurements thực tế từ DNIIT ChirpStack export.

Nguồn: r-dt/response_1777987550466.json (master uplink dump, ~10k record,
3 device, 11 gateway, AS923-2, từ 2025-11-19 → 2026-02-17).

Mỗi (uplink record, rxInfo entry) → 1 survey measurement:
  - location  = vị trí device (object.gnss_latitude / gnss_longitude)
  - rssi/snr  = từ rxInfo[i].rssi/snr (giá trị gateway nhận được)
  - sf        = txInfo.modulation.lora.spreadingFactor
  - freq_mhz  = txInfo.frequency / 1e6  (carrier thực, ví dụ 921.4)
  - device_id = deviceInfo.deviceName  (board01 / node01 / node3)
  - serving_gateway_id = lookup geo.gateways.code = rxInfo.gatewayId.lower()

Filter (skip silently, đếm):
  - object.gnss_latitude == 0 hoặc gnss_longitude == 0  (chưa fix GPS)
  - rxInfo rỗng                                          (không gateway nào nghe)
  - rssi ngoài [-150, -30]  / snr ngoài [-30, 30]        (vi phạm CHECK)
  - sf ngoài [7, 12]                                     (vi phạm CHECK)
  - gatewayId không có trong geo.gateways                (chưa seed)

KHÔNG làm sạch dữ liệu (= scope của data dev). Chỉ filter cứng theo schema.
KHÔNG validate / reputation-weight (= scope của worker-service).

Per system-architecture.md §4.2 + data-architecture.md §14.1, runtime upload
phải qua quarantine. Đây là **fixture seed**, không phải runtime upload, nên
insert thẳng vào CẢ HAI bảng (cùng tinh thần seed cũ — comment trong file
trước nói: "đã coi là 'promoted' seed data, không qua quarantine").

Idempotent: clear theo uploader_id cố định (DNIIT_UPLOADER_ID) rồi insert lại.

Chạy:
    cd /e/DATN/lora-coverage
    export DATABASE_URL=postgresql+psycopg://lora_user:lora_pass_2024@localhost:5432/lora_coverage
    uv run --project services/api-service python migrations/seeds/seed_surveys_danang.py

Env optional:
    SEED_FILE   default: r-dt/response_1777987550466.json
    BATCH_SIZE  default: 500  (rows per executemany)
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEED_FILE = REPO_ROOT / "r-dt" / "response_1777987550466.json"

# Uploader cố định cho fixture DNIIT — dùng để clear/re-seed idempotent.
DNIIT_UPLOADER_ID = UUID("d0001175-d0a0-d000-d000-d0001175d000")

RSSI_MIN, RSSI_MAX = -150.0, -30.0
SNR_MIN, SNR_MAX = -30.0, 30.0
SF_MIN, SF_MAX = 7, 12


def _stream_records(path: Path) -> Iterator[dict[str, Any]]:
    arr = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(arr, list):
        raise ValueError(f"{path} không phải JSON array")
    yield from arr


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    # ChirpStack timestamp có dạng ISO 8601, có thể có offset.
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _gateway_lookup(engine) -> dict[str, str]:
    """Map: lowercase gateway code → uuid (text)."""
    sql = text("SELECT code, id::text FROM geo.gateways")
    with engine.connect() as conn:
        return {r[0].lower(): r[1] for r in conn.execute(sql).all()}


def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL chưa set.", file=sys.stderr)
        return 2

    seed_path = Path(os.environ.get("SEED_FILE") or DEFAULT_SEED_FILE)
    if not seed_path.exists():
        print(f"ERROR: seed file không tồn tại: {seed_path}", file=sys.stderr)
        return 2

    batch_size = int(os.environ.get("BATCH_SIZE") or 500)

    engine = create_engine(db_url, future=True)
    gw_map = _gateway_lookup(engine)
    if not gw_map:
        print(
            "ERROR: geo.gateways trống. Chạy migrations/seeds/seed_gateways.sql trước.",
            file=sys.stderr,
        )
        return 1
    print(f"Loaded {len(gw_map)} gateways từ DB.")

    # Counters
    total = 0
    skip_no_gnss = 0
    skip_no_rxinfo = 0
    skip_unknown_gw = 0
    skip_check = 0
    skip_no_sf = 0
    accepted: list[dict[str, Any]] = []

    for rec in _stream_records(seed_path):
        total += 1

        obj = rec.get("object") or {}
        lat_raw = obj.get("gnss_latitude")
        lon_raw = obj.get("gnss_longitude")
        # Một số file dùng đơn vị int ×1e7 (board01: gnss_latitude=160729548).
        # Heuristic: |val| > 1000 → assume scaled, chia 1e7. Nếu trong dải tọa
        # độ hợp lệ thì giữ nguyên.
        if lat_raw is None or lon_raw is None:
            skip_no_gnss += 1
            continue
        lat = float(lat_raw) / 1e7 if abs(float(lat_raw)) > 1000 else float(lat_raw)
        lon = float(lon_raw) / 1e7 if abs(float(lon_raw)) > 1000 else float(lon_raw)
        if lat == 0.0 or lon == 0.0:
            skip_no_gnss += 1
            continue

        rx_list = rec.get("rxInfo") or []
        if not rx_list:
            skip_no_rxinfo += 1
            continue

        tx = (rec.get("txInfo") or {})
        lora = ((tx.get("modulation") or {}).get("lora") or {})
        sf = lora.get("spreadingFactor")
        if sf is None or not (SF_MIN <= int(sf) <= SF_MAX):
            skip_no_sf += 1
            continue
        sf = int(sf)

        freq_hz = tx.get("frequency")
        freq_mhz = float(freq_hz) / 1e6 if freq_hz else 923.0

        device_id = ((rec.get("deviceInfo") or {}).get("deviceName")) or None
        record_time = _parse_ts(rec.get("time"))

        for rx in rx_list:
            gw_code = (rx.get("gatewayId") or "").lower()
            if not gw_code:
                skip_unknown_gw += 1
                continue
            gw_uuid = gw_map.get(gw_code)
            if not gw_uuid:
                skip_unknown_gw += 1
                continue

            rssi = rx.get("rssi")
            snr = rx.get("snr")
            if rssi is None or snr is None:
                skip_check += 1
                continue
            rssi_f = float(rssi)
            snr_f = float(snr)
            if not (RSSI_MIN <= rssi_f <= RSSI_MAX) or not (SNR_MIN <= snr_f <= SNR_MAX):
                skip_check += 1
                continue

            ts = _parse_ts(rx.get("gwTime")) or record_time
            if ts is None:
                skip_check += 1
                continue

            accepted.append(
                {
                    "id": uuid4(),
                    "ts": ts,
                    "lat": lat,
                    "lon": lon,
                    "rssi": rssi_f,
                    "snr": snr_f,
                    "sf": sf,
                    "freq": freq_mhz,
                    "device_id": device_id,
                    "gw_id": gw_uuid,
                    "uploader_id": DNIIT_UPLOADER_ID,
                }
            )

    print(
        f"Parsed {total} records → {len(accepted)} measurements accepted. "
        f"Skipped: no_gnss={skip_no_gnss}, no_rxinfo={skip_no_rxinfo}, "
        f"unknown_gw={skip_unknown_gw}, check_fail={skip_check}, no_sf={skip_no_sf}."
    )
    if not accepted:
        print("Không có measurement hợp lệ — abort.", file=sys.stderr)
        return 1

    # ── Idempotent: clear dữ liệu DNIIT cũ + legacy fake seed cũ ──────────
    # Legacy fake seed v0 dùng uploader_id 11111111... và device_id 'seed-danang-%'.
    legacy_uploader = UUID("11111111-1111-1111-1111-111111111111")
    with engine.begin() as conn:
        d_q = conn.execute(
            text(
                "DELETE FROM ts.survey_quarantine "
                "WHERE uploader_id IN (:u, :legacy) "
                "OR device_id LIKE 'seed-danang-%'"
            ),
            {"u": DNIIT_UPLOADER_ID, "legacy": legacy_uploader},
        ).rowcount
        d_t = conn.execute(
            text(
                "DELETE FROM ts.survey_training "
                "WHERE uploader_id IN (:u, :legacy) "
                "OR device_id LIKE 'seed-danang-%'"
            ),
            {"u": DNIIT_UPLOADER_ID, "legacy": legacy_uploader},
        ).rowcount
        if d_q or d_t:
            print(f"Cleared cũ: quarantine={d_q}, training={d_t}.")

    # ── Insert vào CẢ quarantine LẪN training ─────────────────────────────
    insert_q = text(
        """
        INSERT INTO ts.survey_quarantine (
            id, timestamp, location, rssi_dbm, snr_db,
            spreading_factor, frequency_mhz, device_id,
            serving_gateway_id, uploader_id
        ) VALUES (
            :id, :ts,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :rssi, :snr, :sf, :freq, :device_id, :gw_id, :uploader_id
        )
        """
    )
    insert_t = text(
        """
        INSERT INTO ts.survey_training (
            id, timestamp, location, rssi_dbm, snr_db,
            spreading_factor, frequency_mhz, device_id,
            serving_gateway_id, uploader_id
        ) VALUES (
            :id, :ts,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :rssi, :snr, :sf, :freq, :device_id, :gw_id, :uploader_id
        )
        """
    )

    with engine.begin() as conn:
        for i in range(0, len(accepted), batch_size):
            chunk = accepted[i : i + batch_size]
            conn.execute(insert_q, chunk)
            conn.execute(insert_t, chunk)
            print(f"  inserted {min(i + batch_size, len(accepted))}/{len(accepted)}")

    print(f"Done: {len(accepted)} rows × 2 bảng = {2 * len(accepted)} insert thành công.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
