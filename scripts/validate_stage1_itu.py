"""Validate Stage 1 ITU-R P.1812 + P.2108 trên test holdout.

Replay không expressable trong SQL — DEM lookup + diffraction chạy qua C++.

Flow:
  1. Settings (LORA_DB_URL, LORA_DEM_DIRECTORY, train/test split dates).
  2. Query ts.survey_training trong test window (2026-01-01 → 2026-02-28).
  3. Build Stage1ItuModel + CrcCovlibBackend.
  4. Predict uplink_rssi_dbm cho từng row → residual = measured - predicted.
  5. Report: bias, σ, RMSE, MAE, count, by-SF breakdown, by-distance breakdown.

Usage:
    uv run python -m scripts.validate_stage1_itu
    uv run python -m scripts.validate_stage1_itu --bbox danang  # default
    uv run python -m scripts.validate_stage1_itu --bbox haiphong --start 2026-02-01

Tại sao Python script, không SQL: ITU stack cần DEM I/O + crc-covlib runtime.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API_SRC = _REPO_ROOT / "services" / "api-service" / "src"
_ML_SRC = _REPO_ROOT / "services" / "ml-service-predict" / "src"
for p in (str(_API_SRC), str(_ML_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)


log = logging.getLogger(__name__)


# Bbox preset — khớp project_stage1_calibration_scope (Đà Nẵng) +
# project_hmap_scope_danang_only (Hải Phòng defer cho training nhưng dùng validation).
_BBOX_PRESETS: dict[str, tuple[float, float, float, float]] = {
    "danang": (15.8, 16.3, 107.9, 108.5),
    "haiphong": (20.7, 21.0, 106.55, 106.85),
}


@dataclass(frozen=True, slots=True)
class _Bucket:
    name: str
    n: int
    bias_db: float
    sigma_db: float
    rmse_db: float
    mae_db: float


def _stats(residual: np.ndarray, name: str) -> _Bucket:
    if residual.size == 0:
        return _Bucket(name=name, n=0, bias_db=0.0, sigma_db=0.0, rmse_db=0.0, mae_db=0.0)
    return _Bucket(
        name=name,
        n=int(residual.size),
        bias_db=float(np.mean(residual)),
        sigma_db=float(np.std(residual, ddof=1)) if residual.size > 1 else 0.0,
        rmse_db=float(np.sqrt(np.mean(residual**2))),
        mae_db=float(np.mean(np.abs(residual))),
    )


def _fetch_test_rows(settings, bbox: tuple[float, float, float, float], start: str, end: str):
    """Lazy-import psycopg để --help không yêu cầu DB driver."""
    import psycopg

    min_lat, max_lat, min_lon, max_lon = bbox
    # Schema dùng PostGIS geography(Point,4326) → ST_Y=lat, ST_X=lon.
    sql = """
        SELECT t.timestamp,
               ST_Y(t.location::geometry) AS lat,
               ST_X(t.location::geometry) AS lon,
               t.rssi_dbm, t.snr_db, t.spreading_factor,
               t.serving_gateway_id,
               gw.code, gw.name, gw.altitude_m, gw.antenna_height_m,
               gw.antenna_gain_dbi, gw.tx_power_dbm, gw.frequency_mhz,
               ST_Y(gw.location::geometry) AS gw_lat,
               ST_X(gw.location::geometry) AS gw_lon
        FROM ts.survey_training t
        JOIN geo.gateways gw ON gw.id = t.serving_gateway_id
        WHERE t.timestamp >= %s::date AND t.timestamp <= %s::date
          AND ST_Y(t.location::geometry) BETWEEN %s AND %s
          AND ST_X(t.location::geometry) BETWEEN %s AND %s
          AND t.serving_gateway_id IS NOT NULL
    """
    log.info("Querying test window %s..%s in bbox=%s", start, end, bbox)
    with psycopg.connect(settings.db_url) as conn, conn.cursor() as cur:
        cur.execute(sql, (start, end, min_lat, max_lat, min_lon, max_lon))
        return cur.fetchall()


def _run(args) -> int:
    from lora_coverage_api.application.itu.model import Stage1ItuModel
    from lora_coverage_api.application.path_loss import resolve_environment_profile
    from lora_coverage_api.domain.coverage import Gateway, GatewayId, Target
    from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend
    from lora_ml_predict.config import get_settings

    settings = get_settings()
    bbox = _BBOX_PRESETS[args.bbox]
    rows = _fetch_test_rows(settings, bbox, args.start, args.end)
    if not rows:
        log.error("Zero rows in test window — nothing to validate")
        return 1
    log.info("Fetched %d test samples", len(rows))

    backend = CrcCovlibBackend(
        dem_directory=settings.dem_directory,
        model_version="stage1-validate",
        percent_time=settings.itu_percent_time,
        percent_location=settings.itu_percent_location,
    )
    stage1 = Stage1ItuModel(
        model_version="stage1-validate",
        backend=backend,
        env_profile=resolve_environment_profile(settings.env_profile),
    )

    residuals: list[float] = []
    distances_km: list[float] = []
    sfs: list[int] = []
    n_errors = 0

    import math

    for r in rows:
        try:
            target = Target(
                latitude=float(r[1]),
                longitude=float(r[2]),
                spreading_factor=int(r[5]),
                frequency_mhz=float(r[13]),
            )
            gw = Gateway(
                id=GatewayId(r[6]),
                code=str(r[7]),
                name=str(r[8]),
                latitude=float(r[14]),
                longitude=float(r[15]),
                altitude_m=float(r[9]),
                antenna_height_m=float(r[10]),
                antenna_gain_dbi=float(r[11]),
                tx_power_dbm=float(r[12]),
                frequency_mhz=float(r[13]),
            )
            pred = stage1.predict(target, gw)
            residual = float(r[3]) - pred.uplink_rssi_dbm
            residuals.append(residual)
            sfs.append(int(r[5]))

            r_earth = 6371.0088
            p1, p2 = math.radians(target.latitude), math.radians(gw.latitude)
            dp = math.radians(gw.latitude - target.latitude)
            dl = math.radians(gw.longitude - target.longitude)
            a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
            distances_km.append(2 * r_earth * math.asin(math.sqrt(a)))
        except Exception as e:
            n_errors += 1
            if n_errors <= 5:
                log.warning("Row error (sample %d): %r", n_errors, e)

    if not residuals:
        log.error("All rows failed prediction (n_errors=%d)", n_errors)
        return 1

    arr = np.asarray(residuals, dtype=np.float64)
    sf_arr = np.asarray(sfs, dtype=np.int64)
    d_arr = np.asarray(distances_km, dtype=np.float64)

    overall = _stats(arr, "overall")
    by_sf = [_stats(arr[sf_arr == sf], f"sf={sf}") for sf in sorted(np.unique(sf_arr).tolist())]
    bins = [(0, 2), (2, 5), (5, 10), (10, 20), (20, 50)]
    by_dist = [_stats(arr[(d_arr >= lo) & (d_arr < hi)], f"d=[{lo},{hi}) km") for lo, hi in bins]

    report = {
        "bbox": args.bbox,
        "window": [args.start, args.end],
        "n_samples": int(arr.size),
        "n_errors": n_errors,
        "overall": asdict(overall),
        "by_sf": [asdict(b) for b in by_sf],
        "by_distance_km": [asdict(b) for b in by_dist],
    }
    print(json.dumps(report, indent=2))
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", choices=sorted(_BBOX_PRESETS), default="danang")
    parser.add_argument("--start", default="2026-01-01", help="ISO date inclusive")
    parser.add_argument("--end", default="2026-02-28", help="ISO date inclusive")
    return _run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
