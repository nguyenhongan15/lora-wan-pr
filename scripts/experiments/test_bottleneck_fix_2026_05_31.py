"""Test fix #6 (bottleneck label): so sánh current vs proposed trên holdout.

Current: bottleneck = chiều có (rssi - datasheet_sensitivity) nhỏ hơn.
Proposed: bottleneck = chiều có min(rssi - sens, snr - sf_limit) nhỏ hơn.

Test: chạy /coverage/predict trên N random holdout rows (Jan-Feb 2026, SF12),
parse UL+DL rssi/snr, tính 2 label, báo cáo flip rate + breakdown.

Rate-limit /coverage/predict = 30/min → sleep 2.1s/call.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.request
from collections import Counter

API = "http://localhost:8000/api/v1/coverage/predict"
THROTTLE_S = 2.1

# Phải khớp services/api-service/src/lora_coverage_api/application/path_loss.py
SF_SNR_LIMITS_DB = {7: -7.5, 8: -10.0, 9: -12.5, 10: -15.0, 11: -17.5, 12: -20.0}
GW_SENSITIVITY = {7: -123.0, 8: -126.0, 9: -129.0, 10: -132.0, 11: -134.5, 12: -137.0}
DEVICE_SENSITIVITY = {7: -120.0, 8: -123.0, 9: -126.0, 10: -129.0, 11: -131.5, 12: -134.0}
BOTTLENECK_TIE_DB = 1.0


def _fetch_rows(n: int) -> list[tuple]:
    import psycopg

    sql = """
        SELECT ST_Y(location::geometry) AS lat,
               ST_X(location::geometry) AS lon,
               spreading_factor, frequency_mhz
        FROM ts.survey_training
        WHERE timestamp >= '2026-01-01'::date AND timestamp <= '2026-02-28'::date
          AND ST_Y(location::geometry) BETWEEN 15.8 AND 16.3
          AND ST_X(location::geometry) BETWEEN 107.9 AND 108.5
          AND spreading_factor = 12
          AND serving_gateway_id IS NOT NULL
        ORDER BY random()
        LIMIT %s
    """
    db_url = os.environ["LORA_DB_URL"]
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (n,))
        return cur.fetchall()


def _predict(lat: float, lon: float, sf: int, freq: float) -> dict | None:
    body = json.dumps(
        {
            "latitude": lat,
            "longitude": lon,
            "spreading_factor": sf,
            "frequency_mhz": freq,
            "tx_power_dbm": 14,
            "environment": "outdoor",
        }
    ).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  predict fail: {e}")
        return None


def _current_bottleneck(
    ul_rssi: float, ul_snr: float, dl_rssi: float, dl_snr: float, sf: int
) -> str:
    """Replicate current resolve_bottleneck (rssi-sens margin)."""
    ul_margin = ul_rssi - GW_SENSITIVITY[sf]
    dl_margin = dl_rssi - DEVICE_SENSITIVITY[sf]
    if abs(ul_margin - dl_margin) <= BOTTLENECK_TIE_DB:
        # Status tie-break trong code thật cần STRONG cả 2, ở đây approximate:
        # cứ coi là "downlink" nếu margin tương đương (label ít ý nghĩa, fall-through).
        pass
    return "uplink" if ul_margin <= dl_margin else "downlink"


def _proposed_bottleneck(
    ul_rssi: float, ul_snr: float, dl_rssi: float, dl_snr: float, sf: int
) -> str:
    """min(rssi-sens, snr-sf_limit) — link margin thật."""
    sf_lim = SF_SNR_LIMITS_DB[sf]
    ul_margin = min(ul_rssi - GW_SENSITIVITY[sf], ul_snr - sf_lim)
    dl_margin = min(dl_rssi - DEVICE_SENSITIVITY[sf], dl_snr - sf_lim)
    return "uplink" if ul_margin <= dl_margin else "downlink"


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    random.seed(0)

    rows = _fetch_rows(n)
    print(f"Fetched {len(rows)} holdout SF12 rows.\n")

    flips = 0
    current_counter: Counter[str] = Counter()
    proposed_counter: Counter[str] = Counter()
    details: list[dict] = []

    for i, (lat, lon, sf, freq) in enumerate(rows):
        res = _predict(float(lat), float(lon), int(sf), float(freq))
        time.sleep(THROTTLE_S)
        if res is None:
            continue
        ul = res.get("uplink") or {}
        dl = res.get("downlink") or {}
        if not ul or not dl:
            continue

        cur = _current_bottleneck(
            ul["rssi_dbm"], ul["snr_db"], dl["rssi_dbm"], dl["snr_db"], int(sf)
        )
        prop = _proposed_bottleneck(
            ul["rssi_dbm"], ul["snr_db"], dl["rssi_dbm"], dl["snr_db"], int(sf)
        )
        current_counter[cur] += 1
        proposed_counter[prop] += 1
        if cur != prop:
            flips += 1

        details.append(
            {
                "i": i,
                "lat": lat,
                "lon": lon,
                "ul_rssi": ul["rssi_dbm"],
                "ul_snr": ul["snr_db"],
                "ul_margin_reported": ul.get("margin_db"),
                "dl_rssi": dl["rssi_dbm"],
                "dl_snr": dl["snr_db"],
                "dl_margin_reported": dl.get("margin_db"),
                "api_label": res.get("bottleneck"),
                "current_recomputed": cur,
                "proposed": prop,
                "flip": cur != prop,
            }
        )
        if (i + 1) % 10 == 0:
            print(f"  ... {i + 1}/{len(rows)}")

    total = len(details)
    print(f"\n== TOTAL n={total}, flips={flips} ({100 * flips / total:.1f}%) ==")
    print("Current  distribution:", dict(current_counter))
    print("Proposed distribution:", dict(proposed_counter))
    print("\n== 8 FLIP SAMPLES (cell có label đảo chiều) ==")
    flipped = [d for d in details if d["flip"]][:8]
    for d in flipped:
        ul_min = min(d["ul_rssi"] - GW_SENSITIVITY[12], d["ul_snr"] - SF_SNR_LIMITS_DB[12])
        dl_min = min(d["dl_rssi"] - DEVICE_SENSITIVITY[12], d["dl_snr"] - SF_SNR_LIMITS_DB[12])
        print(
            f"  ({d['lat']:.4f},{d['lon']:.4f})  UL r={d['ul_rssi']:.1f} s={d['ul_snr']:.1f} "
            f"min_margin={ul_min:.1f}  DL r={d['dl_rssi']:.1f} s={d['dl_snr']:.1f} min_margin={dl_min:.1f}  "
            f"current→{d['current_recomputed']}  proposed→{d['proposed']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
