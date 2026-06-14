"""Eval /api/v1/coverage/predict trên hold-out Jan-Feb 2026.

Khác biệt với `eval_extra_trees_holdout.py`:
  * Script kia gọi model joblib trực tiếp (offline path) → đo accuracy model.
  * Script này gọi HTTP API → đo accuracy của những gì user thực sự thấy.
  * Gap giữa hai script = wiring drift serve-side
    (xem memory `project_api_offline_gap_2026_05_31.md`).

Survey ghi RSSI/SNR mà gateway nhận từ device → so với uplink direction
trong response (không phải top-level — top-level = downlink per backward compat).

Lưu ý: API tự chọn serving gateway theo bottleneck margin. Nếu API pick gw
khác với measured row → vẫn ghi nhận nhưng track gw_mismatch_rate riêng.

Usage:
    LORA_DB_URL=postgresql://lora:lora@localhost:5432/lora \
        uv run --with httpx --with "psycopg[binary]" --with numpy --with pandas \
        python scripts/eval_api_predict_holdout.py
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = REPO_ROOT / "reports" / "seven-train"

EARTH_RADIUS_KM = 6371.0088

# Reference baselines (memory: project_api_offline_gap_2026_05_31.md)
OFFLINE_RMSE_DB = 10.58
OFFLINE_BIAS_DB = -0.25
API_RMSE_DB_LAST = 13.47
API_BIAS_DB_LAST = 4.55


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(a, 1.0)))


def fetch_gateways(db_url: str, bbox: tuple[float, float, float, float]) -> list[dict]:
    """All gateway (id, lat, lon) trong bbox để compute top-N nearest cho Drift 3."""
    import psycopg

    min_lat, max_lat, min_lon, max_lon = bbox
    sql = """
        SELECT gw.id::text AS id,
               ST_Y(gw.location::geometry) AS lat,
               ST_X(gw.location::geometry) AS lon
          FROM geo.gateways gw
         WHERE ST_Y(gw.location::geometry) BETWEEN %s AND %s
           AND ST_X(gw.location::geometry) BETWEEN %s AND %s
    """
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql, [min_lat, max_lat, min_lon, max_lon])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]


def fetch_rows(
    db_url: str,
    start: str,
    end: str,
    bbox: tuple[float, float, float, float],
    max_link_km: float,
    limit: int | None,
) -> list[dict]:
    import psycopg

    min_lat, max_lat, min_lon, max_lon = bbox
    # DISTINCT ON (timestamp, device_id) + ORDER BY rssi DESC: nếu 1 packet
    # được nhiều gw nhận (cùng timestamp + device), chỉ giữ row có RSSI cao
    # nhất → tránh apples-vs-oranges khi /predict pick gw khác.
    sql = """
        SELECT DISTINCT ON (t.timestamp, COALESCE(t.device_id, ''))
               t.timestamp,
               ST_Y(t.location::geometry) AS lat,
               ST_X(t.location::geometry) AS lon,
               t.rssi_dbm,
               t.snr_db,
               t.spreading_factor,
               t.frequency_mhz,
               t.serving_gateway_id::text,
               gw.code,
               ST_Y(gw.location::geometry) AS gw_lat,
               ST_X(gw.location::geometry) AS gw_lon
        FROM ts.survey_training t
        JOIN geo.gateways gw ON gw.id = t.serving_gateway_id
        WHERE t.timestamp >= %s::date AND t.timestamp <= %s::date
          AND ST_Y(t.location::geometry) BETWEEN %s AND %s
          AND ST_X(t.location::geometry) BETWEEN %s AND %s
          AND t.serving_gateway_id IS NOT NULL
          AND ST_DistanceSphere(t.location::geometry, gw.location::geometry) < %s
        ORDER BY t.timestamp, COALESCE(t.device_id, ''), t.rssi_dbm DESC
    """
    params: list = [start, end, min_lat, max_lat, min_lon, max_lon, max_link_km * 1000.0]
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]


def call_api(client, base: str, row: dict, log) -> dict | None:
    payload = {
        "latitude": float(row["lat"]),
        "longitude": float(row["lon"]),
        "spreading_factor": int(row["spreading_factor"]),
        "frequency_mhz": float(row["frequency_mhz"]),
    }
    try:
        r = client.post(f"{base}/api/v1/coverage/predict", json=payload, timeout=30.0)
        if r.status_code != 200:
            log.warning("HTTP %d for %s: %s", r.status_code, payload, r.text[:200])
            return None
        return r.json()
    except Exception as exc:
        log.warning("Exception for %s: %s", payload, exc)
        return None


def metrics(err) -> dict:
    import numpy as np

    err = np.asarray(err, dtype=float)
    if len(err) == 0:
        return {"n": 0}
    return {
        "n": len(err),
        "rmse_db": float(np.sqrt(np.mean(err**2))),
        "mae_db": float(np.mean(np.abs(err))),
        "bias_db": float(np.mean(err)),  # measured - predicted; >0 = model under-predicts
        "p50_abs_db": float(np.median(np.abs(err))),
        "p90_abs_db": float(np.percentile(np.abs(err), 90)),
    }


def bin_metrics(records: list[dict], key: str, bins: list) -> list[dict]:
    out = []
    for lo, hi in bins:
        sub = [r for r in records if lo <= r[key] < hi]
        if not sub:
            continue
        m = metrics([r["rssi_err"] for r in sub])
        m["bin"] = f"{lo}-{hi}"
        m["snr"] = metrics([r["snr_err"] for r in sub])
        out.append(m)
    return out


def per_sf_metrics(records: list[dict]) -> list[dict]:
    out = []
    for sf in range(7, 13):
        sub = [r for r in records if r["sf"] == sf]
        if not sub:
            continue
        m = metrics([r["rssi_err"] for r in sub])
        m["sf"] = sf
        m["snr"] = metrics([r["snr_err"] for r in sub])
        out.append(m)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2026-01-01")
    p.add_argument("--end", default="2026-02-28")
    p.add_argument("--bbox", choices=["danang", "haiphong", "vietnam"], default="danang")
    p.add_argument("--max-link-km", type=float, default=50.0)
    p.add_argument("--api-base", default=os.environ.get("LORA_API_BASE", "http://localhost:8000"))
    p.add_argument("--db-url", default=os.environ.get("LORA_DB_URL"))
    p.add_argument("--limit", type=int, default=None, help="Cap rows for quick smoke")
    p.add_argument(
        "--throttle-s",
        type=float,
        default=2.1,
        help="Sleep giữa các request để né rate limit 30/minute (default 2.1s).",
    )
    p.add_argument("--out", type=Path, default=REPORT_DIR / "holdout_api_eval.json")
    args = p.parse_args()

    bbox_presets = {
        "danang": (15.8, 16.3, 107.9, 108.5),
        "haiphong": (20.7, 21.0, 106.55, 106.85),
        "vietnam": (8.4, 23.4, 102.1, 109.5),
    }
    bbox = bbox_presets[args.bbox]

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    log = logging.getLogger("eval_api")

    if not args.db_url:
        raise SystemExit("LORA_DB_URL not set (env or --db-url)")

    log.info(
        "Query hold-out %s..%s bbox=%s (%s) max_d=%.0fkm limit=%s",
        args.start,
        args.end,
        args.bbox,
        bbox,
        args.max_link_km,
        args.limit,
    )
    rows = fetch_rows(args.db_url, args.start, args.end, bbox, args.max_link_km, args.limit)
    log.info("Fetched %d rows", len(rows))
    if not rows:
        raise SystemExit("No rows in window")

    gateways = fetch_gateways(args.db_url, bbox)
    gw_by_id = {g["id"]: g for g in gateways}
    log.info("Loaded %d gateways for top-N nearest computation", len(gateways))

    log.info("Probing API %s  (throttle=%.2fs)", args.api_base, args.throttle_s)
    import time

    import httpx

    records: list[dict] = []
    gw_mismatch = 0
    sf_match = 0
    api_failed = 0
    top3_match = 0
    api_pick_unknown = 0
    with httpx.Client() as client:
        for i, row in enumerate(rows):
            if i > 0 and args.throttle_s > 0:
                time.sleep(args.throttle_s)
            body = call_api(client, args.api_base, row, log)
            if body is None:
                api_failed += 1
                if (i + 1) % 50 == 0:
                    log.info("  %d / %d  (api_fail=%d)", i + 1, len(rows), api_failed)
                continue

            ul = body.get("uplink") or {}
            pred_rssi = ul.get("rssi_dbm")
            pred_snr = ul.get("snr_db")
            if pred_rssi is None or pred_snr is None:
                api_failed += 1
                continue

            measured_rssi = float(row["rssi_dbm"])
            measured_snr = float(row["snr_db"])
            dist_km = haversine_km(
                float(row["lat"]), float(row["lon"]), float(row["gw_lat"]), float(row["gw_lon"])
            )
            gw_pick_matched = body.get("serving_gateway_id") == row["serving_gateway_id"]
            if not gw_pick_matched:
                gw_mismatch += 1
            if int(body.get("recommended_sf", -1)) == int(row["spreading_factor"]):
                sf_match += 1

            api_pick_id = body.get("serving_gateway_id")
            api_pick = gw_by_id.get(api_pick_id) if api_pick_id else None
            if api_pick is None:
                api_pick_unknown += 1
                api_pick_dist_km = None
                dist_ratio = None
                in_top3 = False
            else:
                api_pick_dist_km = haversine_km(
                    float(row["lat"]),
                    float(row["lon"]),
                    float(api_pick["lat"]),
                    float(api_pick["lon"]),
                )
                dist_ratio = api_pick_dist_km / dist_km if dist_km > 0 else None
                ranked = sorted(
                    gateways,
                    key=lambda g: haversine_km(
                        float(row["lat"]),
                        float(row["lon"]),
                        float(g["lat"]),
                        float(g["lon"]),
                    ),
                )
                top3_ids = {g["id"] for g in ranked[:3]}
                in_top3 = row["serving_gateway_id"] in top3_ids
                if in_top3:
                    top3_match += 1

            records.append(
                {
                    "rssi_err": measured_rssi - float(pred_rssi),
                    "snr_err": measured_snr - float(pred_snr),
                    "sf": int(row["spreading_factor"]),
                    "dist_km": dist_km,
                    "gw_match": gw_pick_matched,
                    "api_pick_dist_km": api_pick_dist_km,
                    "dist_ratio": dist_ratio,
                    "measured_in_top3": in_top3,
                    "path_loss_db": float(body.get("path_loss_db") or 0.0),
                    "model_version": body.get("model_version", ""),
                }
            )
            if (i + 1) % 50 == 0:
                log.info("  %d / %d  (api_fail=%d)", i + 1, len(rows), api_failed)

    if not records:
        raise SystemExit("All API calls failed")

    overall_rssi = metrics([r["rssi_err"] for r in records])
    overall_snr = metrics([r["snr_err"] for r in records])

    dist_bins = bin_metrics(records, "dist_km", [(0, 2), (2, 5), (5, 10), (10, 50)])
    sf_breakdown = per_sf_metrics(records)

    model_versions = sorted({r["model_version"] for r in records if r["model_version"]})

    import numpy as np

    ratios = [r["dist_ratio"] for r in records if r["dist_ratio"] is not None]
    if ratios:
        ratio_arr = np.asarray(ratios)
        gw_pick = {
            "top3_match_rate": top3_match / len(records),
            "dist_ratio_median": float(np.median(ratio_arr)),
            "dist_ratio_p90": float(np.percentile(ratio_arr, 90)),
            "api_pick_unknown": api_pick_unknown,
        }
    else:
        gw_pick = {
            "top3_match_rate": 0.0,
            "dist_ratio_median": None,
            "dist_ratio_p90": None,
            "api_pick_unknown": api_pick_unknown,
        }

    log.info("─" * 60)
    log.info("API /coverage/predict on Jan-Feb 2026 %s hold-out:", args.bbox)
    log.info(
        "  n=%d  (api_fail=%d, gw_mismatch=%d, sf_match=%d)",
        len(records),
        api_failed,
        gw_mismatch,
        sf_match,
    )
    log.info(
        "  RSSI (uplink): RMSE=%.2f  MAE=%.2f  bias=%+.2f  p50|err|=%.2f  p90|err|=%.2f",
        overall_rssi["rmse_db"],
        overall_rssi["mae_db"],
        overall_rssi["bias_db"],
        overall_rssi["p50_abs_db"],
        overall_rssi["p90_abs_db"],
    )
    log.info(
        "  SNR  (uplink): RMSE=%.2f  MAE=%.2f  bias=%+.2f",
        overall_snr["rmse_db"],
        overall_snr["mae_db"],
        overall_snr["bias_db"],
    )
    log.info("  Per distance bin (RSSI):")
    for b in dist_bins:
        log.info(
            "    %s km : RMSE=%.2f bias=%+.2f n=%d", b["bin"], b["rmse_db"], b["bias_db"], b["n"]
        )
    log.info("  Per SF (RSSI):")
    for s in sf_breakdown:
        log.info(
            "    SF%d : RMSE=%.2f bias=%+.2f n=%d", s["sf"], s["rmse_db"], s["bias_db"], s["n"]
        )
    log.info("  GW pick (Drift 3):")
    log.info(
        "    measured-in-top3 nearest = %.1f%%   |   api_pick_unknown=%d",
        gw_pick["top3_match_rate"] * 100,
        gw_pick["api_pick_unknown"],
    )
    if gw_pick["dist_ratio_median"] is not None:
        log.info(
            "    dist_ratio (api_pick / measured) median=%.2f  p90=%.2f",
            gw_pick["dist_ratio_median"],
            gw_pick["dist_ratio_p90"],
        )
    log.info("─" * 60)
    log.info("Reference (memory project_api_offline_gap_2026_05_31):")
    log.info("  offline RMSE=%.2f bias=%+.2f", OFFLINE_RMSE_DB, OFFLINE_BIAS_DB)
    log.info("  API (last)  RMSE=%.2f bias=%+.2f", API_RMSE_DB_LAST, API_BIAS_DB_LAST)
    log.info("─" * 60)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "window": {"start": args.start, "end": args.end},
        "bbox_name": args.bbox,
        "bbox": list(bbox),
        "max_link_km": args.max_link_km,
        "api_base": args.api_base,
        "limit": args.limit,
        "model_versions_seen": model_versions,
        "counts": {
            "rows_fetched": len(rows),
            "evaluated": len(records),
            "api_failed": api_failed,
            "gw_pick_mismatch": gw_mismatch,
            "recommended_sf_match": sf_match,
        },
        "overall_rssi": overall_rssi,
        "overall_snr": overall_snr,
        "per_distance_bin": dist_bins,
        "per_sf": sf_breakdown,
        "gw_pick": gw_pick,
        "reference_baselines": {
            "offline_rmse_db": OFFLINE_RMSE_DB,
            "offline_bias_db": OFFLINE_BIAS_DB,
            "api_rmse_db_last": API_RMSE_DB_LAST,
            "api_bias_db_last": API_BIAS_DB_LAST,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    log.info("Saved → %s", args.out)


if __name__ == "__main__":
    main()
