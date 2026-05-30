"""Test các phương án aggregation RSSI khi 1 cell nhận tín hiệu từ N gateway.

Mục tiêu: chọn cách gộp RSSI cho heatmap "Bản đồ phủ sóng toàn TP" (mode='estimate').

Methods tested (5 numerical + 2 overlay choices = 10 combos):
  A. max(rssi)                         — LoRaWAN-correct: best gateway demodulates
  B. power-sum: 10*log10(sum(10^(rssi/10)))   — total power (physically misleading for LoRa)
  C1. max + 3*(n-1)                    — linear diversity bonus +3dB per extra gw
  C2. max + 10*log10(n)                — log diversity bonus (matches power-sum of equal sources)
  E. mean of top-2 RSSI                — smooth max alternative

Overlay (rendered as opacity/pattern, không đổi color value):
  - none
  - gw_count above sensitivity threshold (-130 dBm)
"""

from __future__ import annotations

import math
import os
import statistics
from collections import defaultdict

import psycopg


def db_url() -> str:
    user = os.environ.get("POSTGRES_USER", "lora_user")
    pwd = os.environ.get("POSTGRES_PASSWORD", "P6asAZLOZQsR1snoOc3O28tJOD0CsXaR")
    db = os.environ.get("POSTGRES_DB", "lora_coverage")
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


SQL = """
SELECT device_id,
       date_trunc('second', timestamp) AS ts_sec,
       ROUND(ST_Y(location::geometry)::numeric, 5) AS lat5,
       ROUND(ST_X(location::geometry)::numeric, 5) AS lon5,
       serving_gateway_id,
       rssi_dbm
FROM ts.survey_training
WHERE serving_gateway_id IS NOT NULL
  AND ST_Y(location::geometry) BETWEEN 15.8 AND 16.3
  AND ST_X(location::geometry) BETWEEN 107.9 AND 108.5
ORDER BY device_id, ts_sec, lat5, lon5
"""


def fetch_events():
    """Group rows by (device, ts_sec, lat, lon). Return only events with N≥2 gw."""
    events: dict[tuple, list[tuple[str, float]]] = defaultdict(list)
    with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
        cur.execute(SQL)
        for row in cur.fetchall():
            device_id, ts_sec, lat5, lon5, gw_id, rssi = row
            key = (device_id, ts_sec, float(lat5), float(lon5))
            events[key].append((str(gw_id), float(rssi)))
    # dedupe per gw (same packet/window) — keep max RSSI per gw to be safe
    multi = {}
    for key, recs in events.items():
        per_gw: dict[str, float] = {}
        for gw_id, rssi in recs:
            if gw_id not in per_gw or rssi > per_gw[gw_id]:
                per_gw[gw_id] = rssi
        if len(per_gw) >= 2:
            multi[key] = sorted(per_gw.values(), reverse=True)  # desc
    return multi


# -------- aggregation methods --------


def agg_max(rssis: list[float]) -> float:
    return max(rssis)


def agg_power_sum(rssis: list[float]) -> float:
    lin = sum(10 ** (r / 10.0) for r in rssis)
    return 10.0 * math.log10(lin)


def agg_max_plus_linear(rssis: list[float], step_db: float = 3.0) -> float:
    return max(rssis) + step_db * (len(rssis) - 1)


def agg_max_plus_log(rssis: list[float]) -> float:
    return max(rssis) + 10.0 * math.log10(len(rssis))


def agg_mean_top2(rssis: list[float]) -> float:
    top = sorted(rssis, reverse=True)[:2]
    return statistics.mean(top)


METHODS = {
    "A_max": agg_max,
    "B_power_sum": agg_power_sum,
    "C1_max+3dB/gw": agg_max_plus_linear,
    "C2_max+10logN": agg_max_plus_log,
    "E_mean_top2": agg_mean_top2,
}


def main():
    print("Fetching survey events...")
    events = fetch_events()
    print(f"Multi-gateway events: n={len(events)}")

    n_by_gw_count: dict[int, int] = defaultdict(int)
    for rssis in events.values():
        n_by_gw_count[len(rssis)] += 1
    print("Distribution:", dict(sorted(n_by_gw_count.items())))

    results: dict[str, list[float]] = {name: [] for name in METHODS}
    deltas_vs_max: dict[str, list[float]] = {name: [] for name in METHODS}
    gw_count_above_thresh = []
    THRESHOLD = -130.0

    for rssis in events.values():
        max_val = max(rssis)
        for name, fn in METHODS.items():
            v = fn(rssis)
            results[name].append(v)
            deltas_vs_max[name].append(v - max_val)
        gw_count_above_thresh.append(sum(1 for r in rssis if r >= THRESHOLD))

    print()
    print("=" * 80)
    print(
        f"{'Method':<18} {'mean(dBm)':>10} {'p50':>8} {'p95':>8} "
        f"{'d vs A_max mean':>16} {'d p95':>8}"
    )
    print("=" * 80)
    for name in METHODS:
        vals = results[name]
        deltas = deltas_vs_max[name]
        print(
            f"{name:<18} {statistics.mean(vals):>10.2f} "
            f"{statistics.median(vals):>8.2f} "
            f"{sorted(vals)[int(0.95 * len(vals))]:>8.2f} "
            f"{statistics.mean(deltas):>16.2f} "
            f"{sorted(deltas)[int(0.95 * len(deltas))]:>8.2f}"
        )
    print()

    # Per-N-gw breakdown for delta vs max
    print("delta vs A_max breakdown by N gateways (mean delta):")
    print(f"{'Method':<18} " + " ".join(f"{f'N={n}':>8}" for n in sorted(n_by_gw_count)))
    by_n_delta: dict[str, dict[int, list[float]]] = {name: defaultdict(list) for name in METHODS}
    for rssis in events.values():
        n = len(rssis)
        max_val = max(rssis)
        for name, fn in METHODS.items():
            by_n_delta[name][n].append(fn(rssis) - max_val)
    for name in METHODS:
        cells = []
        for n in sorted(n_by_gw_count):
            deltas = by_n_delta[name][n]
            cells.append(f"{statistics.mean(deltas):>+8.2f}" if deltas else "    n/a")
        print(f"{name:<18} " + " ".join(cells))
    print()

    print("Overlay: gw_count above -130 dBm")
    overlay_dist: dict[int, int] = defaultdict(int)
    for c in gw_count_above_thresh:
        overlay_dist[c] += 1
    for c in sorted(overlay_dist):
        print(f"  count={c}: {overlay_dist[c]} events ({100 * overlay_dist[c] / len(events):.1f}%)")


if __name__ == "__main__":
    main()
