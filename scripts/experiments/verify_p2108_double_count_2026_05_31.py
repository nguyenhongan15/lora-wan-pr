"""Verify P.2108 double-count với DSM trong Stage 1.

Hypothesis: CrcCovlibBackend cộng cả P.1812 (với DSM) + P.2108 clutter →
DSM đã model diffraction qua building rồi mà P.2108 vẫn add ~20-25 dB
clutter statistic → under-predict RSSI ~26 dB.

Test:
  1. Sample 500 row Đà Nẵng từ DB (Nov-Dec 2025).
  2. Cho mỗi row tính 2 prediction:
     - WITH_P2108: pipeline hiện tại (pl_p1812 + clutter_p2108).
     - NO_P2108: monkey-patch itur_p2108.TerrestrialPathClutterLoss → 0.
  3. Tính bias / RMSE / MAE so với measured rssi.
  4. Per-distance bin breakdown.

Chạy:
    docker cp scripts/experiments/verify_p2108_double_count_2026_05_31.py \\
        lora-wan-api:/tmp/verify_p2108.py
    docker exec lora-wan-api python /tmp/verify_p2108.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("verify_p2108")

BBOX_DANANG = (15.8, 16.3, 107.9, 108.5)
BIN_EDGES = [0, 2, 5, 10, 50]
BIN_LABELS = ["<2km", "2-5km", "5-10km", "10-50km"]
SAMPLE_N = 500


def fetch_rows(n: int):
    import psycopg

    db_url = (os.environ.get("LORA_DB_URL") or os.environ["DATABASE_URL"]).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    min_lat, max_lat, min_lon, max_lon = BBOX_DANANG
    sql = """
        SELECT ST_Y(t.location::geometry) AS lat,
               ST_X(t.location::geometry) AS lon,
               t.rssi_dbm, t.snr_db, t.spreading_factor,
               t.serving_gateway_id,
               gw.code, gw.name, gw.altitude_m, gw.antenna_height_m,
               gw.antenna_gain_dbi, gw.tx_power_dbm, gw.frequency_mhz,
               ST_Y(gw.location::geometry) AS gw_lat,
               ST_X(gw.location::geometry) AS gw_lon
        FROM ts.survey_training t
        JOIN geo.gateways gw ON gw.id = t.serving_gateway_id
        WHERE t.timestamp >= '2025-11-01' AND t.timestamp < '2026-01-01'
          AND ST_Y(t.location::geometry) BETWEEN %s AND %s
          AND ST_X(t.location::geometry) BETWEEN %s AND %s
          AND t.serving_gateway_id IS NOT NULL
          AND ST_DistanceSphere(t.location::geometry, gw.location::geometry) < 50000
        ORDER BY random()
        LIMIT %s
    """
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql, [min_lat, max_lat, min_lon, max_lon, n])
        return cur.fetchall()


def build_stage1():
    _API_SRC = Path("/install/lib/python3.12/site-packages")
    if str(_API_SRC) not in sys.path:
        sys.path.insert(0, str(_API_SRC))
    from lora_coverage_api.application.itu.model import Stage1ItuModel
    from lora_coverage_api.application.path_loss import resolve_environment_profile
    from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend

    surf_raw = os.environ.get("LORA_SURFACE_DEM_DIRECTORY") or ""
    backend = CrcCovlibBackend(
        dem_directory=Path(os.environ["LORA_DEM_DIRECTORY"]),
        surface_dem_directory=Path(surf_raw) if surf_raw else None,
        model_version="verify-p2108",
        percent_time=float(os.environ.get("LORA_ITU_PERCENT_TIME", "50.0")),
        percent_location=float(os.environ.get("LORA_ITU_PERCENT_LOCATION", "50.0")),
    )
    stage1 = Stage1ItuModel(
        model_version="verify-p2108",
        backend=backend,
        env_profile=resolve_environment_profile(os.environ.get("LORA_ENV_PROFILE", "suburban")),
    )
    return stage1


def make_target_gateway(r):
    from lora_coverage_api.domain.coverage import Gateway, GatewayId, Target

    t = Target(
        latitude=float(r[0]),
        longitude=float(r[1]),
        spreading_factor=int(r[4]),
        frequency_mhz=float(r[12]),
    )
    gw = Gateway(
        id=GatewayId(r[5]),
        code=str(r[6]),
        name=str(r[7]),
        latitude=float(r[13]),
        longitude=float(r[14]),
        altitude_m=float(r[8]),
        antenna_height_m=float(r[9]),
        antenna_gain_dbi=float(r[10]),
        tx_power_dbm=float(r[11]),
        frequency_mhz=float(r[12]),
    )
    return t, gw


def predict_all(rows, stage1, label: str):
    measured = []
    predicted = []
    distances = []
    skipped = 0
    for i, r in enumerate(rows):
        try:
            t, gw = make_target_gateway(r)
            pred = stage1.predict(t, gw)
            measured.append(float(r[2]))
            predicted.append(pred.uplink_rssi_dbm)
            # crude haversine
            lat1 = np.radians(t.latitude)
            lat2 = np.radians(gw.latitude)
            dlat = lat2 - lat1
            dlon = np.radians(gw.longitude - t.longitude)
            a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
            distances.append(2 * 6371.0088 * np.arcsin(np.sqrt(min(a, 1.0))))
        except Exception as e:
            skipped += 1
            if skipped <= 3:
                log.warning("[%s] row %d skip: %r", label, i, e)
        if (i + 1) % 100 == 0:
            log.info("[%s] %d/%d (skip=%d)", label, i + 1, len(rows), skipped)
    return (
        np.asarray(measured),
        np.asarray(predicted),
        np.asarray(distances),
        skipped,
    )


def report(name: str, measured: np.ndarray, predicted: np.ndarray, d_km: np.ndarray):
    err = measured - predicted  # residual = measured - predicted; positive = under-predict RSSI
    n = len(err)
    print(f"\n--- {name} (n={n}) ---")
    print(f"  mean(measured)={measured.mean():.2f}  mean(predicted)={predicted.mean():.2f}")
    print(
        f"  residual: mean={err.mean():+.2f}  RMSE={np.sqrt(np.mean(err**2)):.2f}  "
        f"MAE={np.mean(np.abs(err)):.2f}  std={err.std():.2f}"
    )
    print("  per-bin:")
    for i, lbl in enumerate(BIN_LABELS):
        lo, hi = BIN_EDGES[i], BIN_EDGES[i + 1]
        m = (d_km >= lo) & (d_km < hi)
        if m.sum() == 0:
            continue
        e = err[m]
        print(
            f"    {lbl:>8s}: n={int(m.sum()):4d}  bias={e.mean():+6.2f}  "
            f"RMSE={np.sqrt(np.mean(e**2)):5.2f}"
        )


def main():
    log.info("Sampling %d rows from DB...", SAMPLE_N)
    rows = fetch_rows(SAMPLE_N)
    log.info("Got %d rows", len(rows))

    log.info("Building Stage 1 backend...")
    stage1 = build_stage1()

    # --- Run WITH P.2108 (current behavior) ---
    log.info("Predict WITH P.2108 (current pipeline)...")
    meas, pred_with, d, _ = predict_all(rows, stage1, "with_p2108")

    # --- Monkey-patch P.2108 → 0 ---
    log.info("Monkey-patching itur_p2108.TerrestrialPathClutterLoss → 0...")
    from crc_covlib.helper import itur_p2108  # type: ignore[import-untyped]

    original = itur_p2108.TerrestrialPathClutterLoss
    itur_p2108.TerrestrialPathClutterLoss = lambda *a, **kw: 0.0
    try:
        log.info("Predict WITHOUT P.2108...")
        meas2, pred_no, d2, _ = predict_all(rows, stage1, "no_p2108")
    finally:
        itur_p2108.TerrestrialPathClutterLoss = original

    # Sanity: same rows → same measured + distance
    assert np.allclose(meas, meas2), "measured RSSI mismatch — order issue?"
    assert np.allclose(d, d2)

    print("\n" + "=" * 70)
    print(f"VERIFICATION (n={len(meas)} random Đà Nẵng rows, Nov-Dec 2025)")
    print("=" * 70)
    report("WITH P.2108 (current pipeline)", meas, pred_with, d)
    report("WITHOUT P.2108 (P.1812+DSM only)", meas, pred_no, d)

    # Quantify P.2108 contribution magnitude
    p2108_db = (
        pred_no - pred_with
    )  # how much extra loss P.2108 adds (always positive → reduces predicted RSSI)
    print("\n--- P.2108 contribution magnitude ---")
    print(f"  mean P.2108 loss = {p2108_db.mean():.2f} dB")
    print(f"  std  P.2108 loss = {p2108_db.std():.2f} dB")
    print(f"  range = [{p2108_db.min():.2f}, {p2108_db.max():.2f}] dB")
    for i, lbl in enumerate(BIN_LABELS):
        lo, hi = BIN_EDGES[i], BIN_EDGES[i + 1]
        m = (d >= lo) & (d < hi)
        if m.sum() == 0:
            continue
        print(f"    {lbl:>8s}: mean P.2108 add = {p2108_db[m].mean():.2f} dB (n={int(m.sum())})")


if __name__ == "__main__":
    main()
