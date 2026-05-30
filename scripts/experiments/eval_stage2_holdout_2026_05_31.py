"""One-shot Stage 2 accuracy check on hold-out (Jan-Feb 2026, Đà Nẵng).

Đọc /tmp/holdout.csv, POST /api/v1/coverage/predict, so sánh predicted vs
measured RSSI. In MAE/RMSE/bias toàn cục + theo dải khoảng cách.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import urllib.request

API = "http://localhost:8000/api/v1/coverage/predict"


def call_predict(lat: float, lon: float, sf: int, freq: float) -> dict | None:
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
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"predict fail: {e}")
        return None


def bin_distance(km: float) -> str:
    if km < 2:
        return "<2km"
    if km < 5:
        return "2-5km"
    if km < 10:
        return "5-10km"
    return ">=10km"


def main() -> None:
    from pathlib import Path

    csv_path = Path(__file__).parent / "_holdout.csv"
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    print(f"holdout rows={len(rows)}")
    diffs: list[float] = []
    per_bin: dict[str, list[float]] = {}
    n_fail = 0
    for i, r in enumerate(rows):
        lat = float(r["lat"])
        lon = float(r["lon"])
        sf = int(r["spreading_factor"])
        freq = float(r["frequency_mhz"])
        meas = float(r["rssi_dbm"])
        res = call_predict(lat, lon, sf, freq)
        if res is None or res.get("rssi_dbm") is None:
            n_fail += 1
            continue
        pred = float(res["rssi_dbm"])
        d_km = float(res.get("distance_to_serving_gateway_km", float("nan")))
        diff = pred - meas
        diffs.append(diff)
        per_bin.setdefault(bin_distance(d_km), []).append(diff)
        if i % 50 == 0:
            print(f"  ...{i}/{len(rows)} predicted")
    print(f"fail={n_fail}, ok={len(diffs)}")
    if not diffs:
        return
    mae = sum(abs(x) for x in diffs) / len(diffs)
    rmse = math.sqrt(sum(x * x for x in diffs) / len(diffs))
    bias = sum(diffs) / len(diffs)
    print(f"\n== OVERALL (n={len(diffs)}) ==")
    print(f"  MAE  = {mae:.2f} dB")
    print(f"  RMSE = {rmse:.2f} dB")
    print(f"  bias = {bias:+.2f} dB (pred - meas)")
    print(f"  std  = {statistics.pstdev(diffs):.2f} dB")
    print("\n== PER DISTANCE BIN ==")
    for b in ["<2km", "2-5km", "5-10km", ">=10km"]:
        d = per_bin.get(b, [])
        if not d:
            continue
        mae_b = sum(abs(x) for x in d) / len(d)
        rmse_b = math.sqrt(sum(x * x for x in d) / len(d))
        bias_b = sum(d) / len(d)
        print(
            f"  {b:>8s}: n={len(d):4d}  MAE={mae_b:5.2f}  RMSE={rmse_b:5.2f}  bias={bias_b:+5.2f}"
        )


if __name__ == "__main__":
    main()
