"""One-off script: generate CSV test data khớp với Stage1 ITU + DSM model.

Chạy:
  docker cp core-logic/_gen_test_csv.py lora-wan-api:/app/_gen.py
  docker compose exec api-service python /app/_gen.py
  docker cp lora-wan-api:/app/danang_test_data_gw06fcf2_v2.csv core-logic/

Output: 120 rows, RSSI = model.predict() + N(0, 4 dB) → delta thường ≤ 12 dB,
qua threshold L2 cứng nhất (15 dB cho user chưa verified).
"""

from __future__ import annotations

import csv
import math
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lora_coverage_api.domain.coverage import GatewayId, Target
from lora_coverage_api.edge.deps import _engine, trust_validator
from sqlalchemy import text

UTC = UTC
GATEWAY_CODE = "ac1f09fffe06fcf2"
SEED = 42
N_ROWS = 120
NOISE_SIGMA_DB = 4.0
OUT_PATH = "/tmp/danang_test_data_gw06fcf2_v2.csv"


def sf_from_distance(d_km: float) -> int:
    if d_km < 1.5:
        return random.choice([7, 7, 8])
    if d_km < 3.0:
        return random.choice([7, 8, 8, 9])
    if d_km < 5.0:
        return random.choice([8, 9, 9, 10])
    if d_km < 7.0:
        return random.choice([9, 10, 10, 11])
    return random.choice([10, 11, 12, 12])


def main() -> None:
    val = trust_validator()
    with _engine().begin() as conn:
        row = conn.execute(
            text("SELECT id FROM geo.gateways WHERE code=:c"),
            {"c": GATEWAY_CODE},
        ).one()
    gw = val._directory.get_by_id(GatewayId(row.id))
    assert gw is not None

    random.seed(SEED)
    start = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    rows: list[list[object]] = []
    attempts = 0
    while len(rows) < N_ROWS and attempts < 6000:
        attempts += 1
        d_km = random.uniform(0.3, 8.5)
        bearing = random.uniform(0, 2 * math.pi)
        dlat = (d_km / 111.0) * math.cos(bearing)
        dlon = (d_km / (111.0 * math.cos(math.radians(gw.latitude)))) * math.sin(bearing)
        lat = gw.latitude + dlat
        lon = gw.longitude + dlon
        sf = sf_from_distance(d_km)
        target = Target(
            latitude=lat,
            longitude=lon,
            spreading_factor=sf,
            frequency_mhz=923.0,
        )
        try:
            pred = val._model.predict(target, gw).rssi_dbm
        except Exception:
            continue
        if pred < -135 or pred > -45:
            continue
        rssi = max(-145.0, min(-30.0, pred + random.gauss(0, NOISE_SIGMA_DB)))
        snr = max(-20.0, min(10.0, (rssi - -120.0) + random.gauss(0, 1.5)))
        ts = (start + timedelta(minutes=len(rows))).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append(
            [
                ts,
                f"{lat:.4f}",
                f"{lon:.4f}",
                round(rssi),
                f"{snr:.1f}",
                sf,
                GATEWAY_CODE,
                923,
                "demo-dev-1",
            ]
        )

    with Path(OUT_PATH).open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "timestamp",
                "latitude",
                "longitude",
                "rssi_dbm",
                "snr_db",
                "spreading_factor",
                "gateway_code",
                "frequency_mhz",
                "device_id",
            ]
        )
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT_PATH} (attempts={attempts})")


if __name__ == "__main__":
    main()
