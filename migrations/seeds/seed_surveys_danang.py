"""Generate 200 fake survey points trên địa bàn TP. Đà Nẵng.

Quy trình (theo phương án 1 user đã chọn ở v2):
  1. Load 11 gateways DAD-* từ geo.gateways (đã seed bằng SQL).
  2. Random 200 điểm (lat, lng) uniform trong bbox đô thị Đà Nẵng.
  3. Với mỗi điểm: tìm gateway gần nhất, dùng Stage 1 model tính RSSI/SNR,
     cộng Gaussian noise σ=6 dB (shadow fading).
  4. Random spreading_factor ∈ {7,9,12}.
  5. Insert thẳng vào ts.survey_training (đã coi là 'promoted' seed data,
     không qua quarantine — vì đây là data sẵn dùng cho ML/demo).

Chạy:
    cd /e/DATN/lora-coverage
    export DATABASE_URL=postgresql+psycopg://lora:change_me@localhost:5432/lora_coverage
    uv run --project services/api-service python migrations/seeds/seed_surveys_danang.py

Idempotent: xoá toàn bộ row có device_id LIKE 'seed-danang-%' rồi insert lại.
"""

from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

# Cho phép import từ api-service mà không cần install package.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "services" / "api-service" / "src"))

from sqlalchemy import create_engine, text  # noqa: E402

from lora_coverage_api.application.path_loss import Stage1LogDistanceModel  # noqa: E402
from lora_coverage_api.domain.coverage import Gateway, GatewayId, Target  # noqa: E402

# ── Đà Nẵng urban bbox (loose, gồm vùng đông & vùng tây sông Hàn) ────────
BBOX_MIN_LON = 108.10
BBOX_MAX_LON = 108.35
BBOX_MIN_LAT = 15.97
BBOX_MAX_LAT = 16.15

N_POINTS = 200
SHADOW_FADING_SIGMA_DB = 6.0
SF_CHOICES = (7, 9, 12)
DEVICE_ID_PREFIX = "seed-danang-"
UPLOADER_ID = UUID("11111111-1111-1111-1111-111111111111")


def _load_gateways(engine) -> list[Gateway]:
    sql = text(
        """
        SELECT
            id, code, name,
            ST_Y(location::geometry) AS lat,
            ST_X(location::geometry) AS lon,
            altitude_m, antenna_height_m, antenna_gain_dbi,
            tx_power_dbm, frequency_mhz
        FROM geo.gateways
        WHERE code LIKE 'DAD-%' AND is_public = true
        ORDER BY code
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).mappings().all()
    return [
        Gateway(
            id=GatewayId(r["id"]),
            code=r["code"],
            name=r["name"],
            latitude=float(r["lat"]),
            longitude=float(r["lon"]),
            altitude_m=float(r["altitude_m"]),
            antenna_height_m=float(r["antenna_height_m"]),
            antenna_gain_dbi=float(r["antenna_gain_dbi"]),
            tx_power_dbm=float(r["tx_power_dbm"]),
            frequency_mhz=float(r["frequency_mhz"]),
        )
        for r in rows
    ]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL chưa set.", file=sys.stderr)
        return 1

    rng = random.Random(42)  # deterministic
    engine = create_engine(db_url, future=True)

    gateways = _load_gateways(engine)
    if len(gateways) < 3:
        print(
            f"ERROR: chỉ thấy {len(gateways)} gateway DAD-* trong DB. "
            "Chạy seed_gateways.sql trước.",
            file=sys.stderr,
        )
        return 1
    print(f"Loaded {len(gateways)} gateways: {[g.code for g in gateways]}")

    model = Stage1LogDistanceModel(model_version="stage1-loglike-v0.1.0")

    # Clear seed cũ
    with engine.begin() as conn:
        deleted = conn.execute(
            text(
                "DELETE FROM ts.survey_training WHERE device_id LIKE :prefix"
            ),
            {"prefix": f"{DEVICE_ID_PREFIX}%"},
        ).rowcount
        if deleted:
            print(f"Cleared {deleted} existing seed rows.")

    # Generate
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    skipped = 0
    for i in range(N_POINTS):
        lat = rng.uniform(BBOX_MIN_LAT, BBOX_MAX_LAT)
        lon = rng.uniform(BBOX_MIN_LON, BBOX_MAX_LON)
        sf = rng.choice(SF_CHOICES)

        # Tìm gateway gần nhất (linear search, 11 cái nên OK).
        nearest = min(
            gateways,
            key=lambda g: _haversine_km(lat, lon, g.latitude, g.longitude),
        )

        target = Target(
            latitude=lat,
            longitude=lon,
            spreading_factor=sf,
            frequency_mhz=nearest.frequency_mhz,
        )
        pred = model.predict(target, nearest)

        # Cộng shadow fading noise (Gaussian σ=6 dB cho RSSI; σ=2 dB cho SNR
        # vì SNR variance ở field thấp hơn nhiều — noise floor là chung).
        noise_rssi = rng.gauss(0.0, SHADOW_FADING_SIGMA_DB)
        noise_snr = rng.gauss(0.0, 2.0)
        # Clamp vào range CHECK constraint (thay vì skip → đủ N_POINTS).
        rssi = max(-150.0, min(-30.0, pred.rssi_dbm + noise_rssi))
        snr = max(-30.0, min(30.0, pred.snr_db + noise_snr))

        # Random timestamp trong 30 ngày qua
        ts = now - timedelta(
            seconds=rng.randint(0, 30 * 24 * 3600),
        )

        rows.append(
            {
                "id": uuid4(),
                "ts": ts,
                "lat": lat,
                "lon": lon,
                "rssi": round(rssi, 2),
                "snr": round(snr, 2),
                "sf": sf,
                "freq": nearest.frequency_mhz,
                "device_id": f"{DEVICE_ID_PREFIX}{i:03d}",
                "gw_id": nearest.id,
                "uploader_id": UPLOADER_ID,
            }
        )

    insert_sql = text(
        """
        INSERT INTO ts.survey_training (
            id, timestamp, location, rssi_dbm, snr_db,
            spreading_factor, frequency_mhz, device_id,
            serving_gateway_id, uploader_id
        )
        VALUES (
            :id, :ts,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :rssi, :snr, :sf, :freq, :device_id, :gw_id, :uploader_id
        )
        """
    )
    with engine.begin() as conn:
        conn.execute(insert_sql, rows)

    print(f"Inserted {len(rows)} survey points (skipped {skipped} out-of-range).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
