"""Seed geo.gateways từ metadata thật trong r-dt/.

Idempotent: chạy lại nhiều lần không tạo duplicate (ON CONFLICT DO UPDATE).

Usage:
    uv run --project services/api-service python scripts/seed_gateways.py

Env:
    DATABASE_URL  postgresql+psycopg://...   (bắt buộc, fail nếu thiếu)
    SEED_FILE     đường dẫn JSON  (default: r-dt/response_1777987688423.json)
    SEED_FREQ_MHZ tần số mặc định (default: 923.0 — AS923-2 ở Đà Nẵng)

Schema r-dt:
    {
      "gateways": [
        {
          "gatewayId": "ac1f09fffe06fcf2",
          "latitude": 16.0547,
          "longitude": 108.2198,
          "altitude": 108.0 | null
        }, ...
      ],
      ...
    }
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEED_FILE = REPO_ROOT / "r-dt" / "response_1777987688423.json"


# Allowed frequencies theo migration 0002 CHECK constraint.
ALLOWED_FREQ_MHZ = (433.0, 868.0, 915.0, 923.0)


def _load_gateways(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw: list[dict[str, Any]] = payload.get("gateways") or []
    if not raw:
        raise ValueError(f"Không thấy 'gateways' trong {path}")
    return raw


def _normalize(row: dict[str, Any], freq_mhz: float) -> dict[str, Any]:
    gw_id = str(row.get("gatewayId", "")).strip().lower()
    if len(gw_id) < 3:
        raise ValueError(f"gatewayId quá ngắn: {row!r}")

    lat = row.get("latitude")
    lon = row.get("longitude")
    if lat is None or lon is None:
        raise ValueError(f"thiếu latitude/longitude: {row!r}")

    # Antenna metadata: outdoor LoRa thực tế phổ biến (khớp seed_gateways.sql).
    # Operator phải verify khi có spec thật.
    return {
        "code": gw_id,
        "name": f"Gateway {gw_id[-6:]}",  # last 6 hex để đọc cho người
        "lat": float(lat),
        "lon": float(lon),
        "altitude_m": float(row.get("altitude") or 0.0),
        "antenna_height_m": 15.0,
        "antenna_gain_dbi": 5.0,
        "tx_power_dbm": 14.0,
        "freq": freq_mhz,
    }


# UPSERT: ON CONFLICT (code) → giữ id cũ, chỉ refresh các cột metadata.
# `code` là natural key duy nhất → upsert chính xác.
_UPSERT_SQL = text(
    """
    INSERT INTO geo.gateways (
        code, name, location, altitude_m, antenna_height_m, antenna_gain_dbi,
        tx_power_dbm, frequency_mhz, is_public
    ) VALUES (
        :code, :name,
        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
        :altitude_m, :antenna_height_m, :antenna_gain_dbi,
        :tx_power_dbm, :freq, true
    )
    ON CONFLICT (code) DO UPDATE SET
        name = EXCLUDED.name,
        location = EXCLUDED.location,
        altitude_m = EXCLUDED.altitude_m,
        antenna_height_m = EXCLUDED.antenna_height_m,
        antenna_gain_dbi = EXCLUDED.antenna_gain_dbi,
        tx_power_dbm = EXCLUDED.tx_power_dbm,
        frequency_mhz = EXCLUDED.frequency_mhz
    RETURNING (xmax = 0) AS inserted, id;
    """
)


def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL chưa set.", file=sys.stderr)
        return 2

    seed_path = Path(os.environ.get("SEED_FILE") or DEFAULT_SEED_FILE)
    if not seed_path.exists():
        print(f"ERROR: seed file không tồn tại: {seed_path}", file=sys.stderr)
        return 2

    freq_raw = float(os.environ.get("SEED_FREQ_MHZ") or 923.0)
    if freq_raw not in ALLOWED_FREQ_MHZ:
        print(
            f"ERROR: SEED_FREQ_MHZ={freq_raw} không thuộc {ALLOWED_FREQ_MHZ}",
            file=sys.stderr,
        )
        return 2

    rows = _load_gateways(seed_path)
    normalized = [_normalize(r, freq_raw) for r in rows]
    print(f"Sẽ upsert {len(normalized)} gateway từ {seed_path.name} @ {freq_raw} MHz")

    engine = create_engine(db_url, future=True)
    inserted = 0
    updated = 0
    with engine.begin() as conn:
        for r in normalized:
            row = conn.execute(_UPSERT_SQL, r).mappings().one()
            if row["inserted"]:
                inserted += 1
            else:
                updated += 1
            print(f"  {'+' if row['inserted'] else '~'} {r['code']}  {r['lat']:.5f},{r['lon']:.5f}")

    print(f"Done: inserted={inserted}  updated={updated}  total={len(normalized)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
