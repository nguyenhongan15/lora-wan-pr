"""Collect training data từ Postgres → pandas DataFrame có residual + 7 feature.

Plan v1 §4.1. Áp dụng quyết định Q6:
  - Đà Nẵng bbox only (project_stage1_calibration_scope).
  - Time split: train+val Nov-Dec 2025, test Jan-Feb 2026.
  - KHÔNG filter distance ≥ 5km — để LightGBM tự học bias < 2 km.

Pipeline:
  1. SQL query → rows (timestamp, lat, lon, rssi, snr, sf, serving_gw, gw cols).
  2. Stage1ItuModel.predict() (ITU-R P.1812 + P.2108) → rssi_stage1 → residual = measured - stage1.
  3. FeaturePipeline.extract() → 7 feature columns.
  4. Trả DataFrame: 7 feature cols + residual + (lat, lon) + split label.

Format trả pandas DataFrame thay vì numpy array: LightGBM ăn DataFrame trực tiếp;
column name = source of truth cho feature_importance + serving-time schema check.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd
import psycopg
from lora_coverage_api.application.itu.model import Stage1ItuModel
from lora_coverage_api.application.path_loss import resolve_environment_profile
from lora_coverage_api.domain.coverage import Gateway, GatewayId, Target
from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend

from ..config import Settings
from ..features.dem import DemLookup
from ..features.extractor import FeaturePipeline
from ..features.osm import UrbanizationLookup

log = logging.getLogger(__name__)


# Column names — single source of truth cho training + serving feature schema.
# Order TỐI QUAN TRỌNG: stage2_residual.py builds ndarray theo đúng order này.
FEATURE_COLUMNS: tuple[str, ...] = (
    "log10_distance_to_serving_gw_km",
    "bearing_sin",
    "bearing_cos",
    "distance_to_2nd_nearest_gw_km",
    "elevation_diff_m",
    "los_obstruction_count",
    "urbanization_index",
    "spreading_factor",
    "frequency_mhz",
    "gw_antenna_height_m",
    "gw_antenna_gain_dbi",
    "serving_gateway_id",
)

# Categorical features cho LightGBM native handling. Pandas category dtype được
# auto-detect khi `categorical_feature='auto'` ở lgb.Dataset; chúng ta truyền
# tường minh ở retrain.py để rõ ràng + chống regression khi thêm cột mới.
#   - serving_gateway_id: UUID string, LightGBM dùng default-direction cho
#     unseen gateway tại serving time.
#   - spreading_factor: int discrete (7,10,12), treat categorical thay vì
#     ordinal cho phép GBM split không-monotone.
CATEGORICAL_FEATURES: tuple[str, ...] = (
    "serving_gateway_id",
    "spreading_factor",
)


@dataclass(frozen=True, slots=True)
class TrainingFrame:
    """Bundle DataFrame + cột tên cố định để downstream khỏi đoán schema.

    `train_val` + `test` đã split sẵn theo Q6 time-split rule.
    """

    train_val: pd.DataFrame
    test: pd.DataFrame
    feature_columns: tuple[str, ...]
    target_column: str  # "residual_db"


# ── SQL ───────────────────────────────────────────────────────────────────────
# JOIN survey_training ↔ gateways: ta cần gateway altitude + antenna_height cho
# DEM LoS raycast + đầy đủ link-budget config cho Stage1 predict.
#
# WHERE clause:
#   - bbox Đà Nẵng (lat 15.8-16.3, lon 107.9-108.5).
#   - serving_gateway_id IS NOT NULL (residual chỉ có nghĩa khi biết serving gw).
#   - timestamp ≤ test_end (sau đó train pipeline tự split theo train_val_end).
#
# ORDER BY timestamp: deterministic, hỗ trợ debug + reproducibility.
_SURVEY_QUERY = """
SELECT
    s.id,
    s.timestamp,
    ST_Y(s.location::geometry) AS lat,
    ST_X(s.location::geometry) AS lon,
    s.rssi_dbm,
    s.snr_db,
    s.spreading_factor,
    s.frequency_mhz,
    s.serving_gateway_id,
    g.code           AS gw_code,
    g.name           AS gw_name,
    ST_Y(g.location::geometry) AS gw_lat,
    ST_X(g.location::geometry) AS gw_lon,
    g.altitude_m     AS gw_altitude_m,
    g.antenna_height_m AS gw_antenna_height_m,
    g.antenna_gain_dbi AS gw_antenna_gain_dbi,
    g.tx_power_dbm   AS gw_tx_power_dbm,
    g.frequency_mhz  AS gw_frequency_mhz
FROM ts.survey_training s
JOIN geo.gateways g ON g.id = s.serving_gateway_id
WHERE s.serving_gateway_id IS NOT NULL
  AND ST_Y(s.location::geometry) BETWEEN %(min_lat)s AND %(max_lat)s
  AND ST_X(s.location::geometry) BETWEEN %(min_lon)s AND %(max_lon)s
  AND s.timestamp >= %(start)s
  AND s.timestamp <= %(end)s
ORDER BY s.timestamp
"""


def _fetch_rows(settings: Settings) -> pd.DataFrame:
    """Run SQL query và trả raw rows (1 row per survey sample)."""
    with psycopg.connect(settings.db_url) as conn, conn.cursor() as cur:
        cur.execute(
            _SURVEY_QUERY,
            {
                "min_lat": settings.train_bbox_min_lat,
                "max_lat": settings.train_bbox_max_lat,
                "min_lon": settings.train_bbox_min_lon,
                "max_lon": settings.train_bbox_max_lon,
                "start": settings.train_val_start,
                "end": settings.test_end,
            },
        )
        cols = [d.name for d in cur.description] if cur.description else []
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def _load_all_gateways(settings: Settings) -> list[Gateway]:
    """All gateways trong bbox — dùng cho FeaturePipeline candidate list (2nd nearest)."""
    query = """
    SELECT
        id, code, name,
        ST_Y(location::geometry) AS lat,
        ST_X(location::geometry) AS lon,
        altitude_m, antenna_height_m, antenna_gain_dbi, tx_power_dbm, frequency_mhz
    FROM geo.gateways
    WHERE ST_Y(location::geometry) BETWEEN %(min_lat)s AND %(max_lat)s
      AND ST_X(location::geometry) BETWEEN %(min_lon)s AND %(max_lon)s
    """
    with psycopg.connect(settings.db_url) as conn, conn.cursor() as cur:
        cur.execute(
            query,
            {
                "min_lat": settings.train_bbox_min_lat,
                "max_lat": settings.train_bbox_max_lat,
                "min_lon": settings.train_bbox_min_lon,
                "max_lon": settings.train_bbox_max_lon,
            },
        )
        rows = cur.fetchall()
    return [
        Gateway(
            id=GatewayId(r[0]),
            code=r[1],
            name=r[2],
            latitude=float(r[3]),
            longitude=float(r[4]),
            altitude_m=float(r[5]),
            antenna_height_m=float(r[6]),
            antenna_gain_dbi=float(r[7]),
            tx_power_dbm=float(r[8]),
            frequency_mhz=float(r[9]),
        )
        for r in rows
    ]


def _row_to_target_gateway(row: pd.Series) -> tuple[Target, Gateway]:
    """Build duck-typed Target + Gateway từ 1 survey row.

    Default device tx_power/gain: dùng AS923-2 cap 14 dBm + 2 dBi whip
    (theo project_fit_script_assumptions memory). Khớp Target dataclass default.
    """
    target = Target(
        latitude=float(row["lat"]),
        longitude=float(row["lon"]),
        spreading_factor=int(row["spreading_factor"]),
        frequency_mhz=float(row["frequency_mhz"]),
    )
    gateway = Gateway(
        id=GatewayId(row["serving_gateway_id"]),
        code=str(row["gw_code"]),
        name=str(row["gw_name"]),
        latitude=float(row["gw_lat"]),
        longitude=float(row["gw_lon"]),
        altitude_m=float(row["gw_altitude_m"]),
        antenna_height_m=float(row["gw_antenna_height_m"]),
        antenna_gain_dbi=float(row["gw_antenna_gain_dbi"]),
        tx_power_dbm=float(row["gw_tx_power_dbm"]),
        frequency_mhz=float(row["gw_frequency_mhz"]),
    )
    return target, gateway


def collect(settings: Settings) -> TrainingFrame:
    """Main entry: SQL fetch → Stage1 residual → feature extract → split.

    Performance: 9.5k DN rows x ~10ms/row (DEM LoS raycast dominates) ≈ 90s.
    Đủ fast cho 1 lần train mỗi tuần, không cần parallel.
    """
    log.info("Fetching survey_training rows from %s", settings.db_url.split("@")[-1])
    raw = _fetch_rows(settings)
    log.info("Fetched %d rows", len(raw))
    if raw.empty:
        msg = "No survey_training rows in Đà Nẵng bbox + time window — cannot train."
        raise RuntimeError(msg)

    log.info("Loading DEM + urbanization rasters")
    dem = DemLookup(str(settings.dem_path))
    urb = UrbanizationLookup(str(settings.urbanization_path))

    log.info("Loading candidate gateways")
    candidates = _load_all_gateways(settings)
    pipeline = FeaturePipeline(
        candidate_gateways=candidates,
        dem_lookup=dem,
        urbanization_lookup=urb,
    )

    env_profile = resolve_environment_profile(settings.env_profile)
    backend = CrcCovlibBackend(
        dem_directory=settings.dem_directory,
        model_version="stage1-training",
        percent_time=settings.itu_percent_time,
        percent_location=settings.itu_percent_location,
    )
    stage1 = Stage1ItuModel(
        model_version="stage1-training",
        backend=backend,
        env_profile=env_profile,
    )

    log.info("Computing Stage1 prediction + features for %d rows", len(raw))
    feature_records: list[dict[str, float]] = []
    residuals: list[float] = []
    for _, row in raw.iterrows():
        target, gateway = _row_to_target_gateway(row)
        pred = stage1.predict(target, gateway)
        # Survey RSSI is uplink (device → gateway). Stage1 uplink_rssi_dbm là DL-direction
        # value khi compute_link_budget gọi direction="uplink" — Prediction populates
        # uplink_rssi_dbm. So we use pred.uplink_rssi_dbm as Stage1 estimate.
        residual = float(row["rssi_dbm"]) - pred.uplink_rssi_dbm
        residuals.append(residual)

        fv = pipeline.extract(target, gateway)
        feature_records.append(
            {
                "log10_distance_to_serving_gw_km": fv.log10_distance_to_serving_gw_km,
                "bearing_sin": fv.bearing_sin,
                "bearing_cos": fv.bearing_cos,
                "distance_to_2nd_nearest_gw_km": fv.distance_to_2nd_nearest_gw_km,
                "elevation_diff_m": fv.elevation_diff_m,
                "los_obstruction_count": fv.los_obstruction_count,
                "urbanization_index": fv.urbanization_index,
                "spreading_factor": fv.spreading_factor,
                "frequency_mhz": fv.frequency_mhz,
                "gw_antenna_height_m": fv.gw_antenna_height_m,
                "gw_antenna_gain_dbi": fv.gw_antenna_gain_dbi,
                "serving_gateway_id": fv.serving_gateway_id,
            }
        )

    feat_df = pd.DataFrame.from_records(feature_records)
    feat_df["residual_db"] = residuals
    feat_df["lat"] = raw["lat"].to_numpy()
    feat_df["lon"] = raw["lon"].to_numpy()
    feat_df["timestamp"] = pd.to_datetime(raw["timestamp"].to_numpy(), utc=True)
    # Measured raw cho downstream evaluation (scatter/CM/ROC trên rssi tổng hợp).
    # Training pipeline KHÔNG dùng cột này — vẫn chỉ select FEATURE_COLUMNS.
    feat_df["rssi_dbm_measured"] = raw["rssi_dbm"].to_numpy(dtype=float)
    feat_df["snr_db_measured"] = raw["snr_db"].to_numpy(dtype=float)

    # Replace inf (no 2nd-nearest GW) by large finite number — LightGBM handles
    # NaN natively nhưng inf khiến optuna metric ra nan. 999 km > VN-wide max.
    inf_mask = feat_df["distance_to_2nd_nearest_gw_km"].isin([float("inf")])
    if inf_mask.any():
        feat_df.loc[inf_mask, "distance_to_2nd_nearest_gw_km"] = 999.0
        log.info("Replaced %d inf 2nd-nearest values → 999.0", int(inf_mask.sum()))

    train_val_end = pd.Timestamp(settings.train_val_end, tz="UTC") + pd.Timedelta(days=1)
    test_start = pd.Timestamp(settings.test_start, tz="UTC")
    train_val_df = feat_df[feat_df["timestamp"] < train_val_end].reset_index(drop=True)
    test_df = feat_df[feat_df["timestamp"] >= test_start].reset_index(drop=True)

    log.info(
        "Split: train+val=%d, test=%d (boundary %s → %s)",
        len(train_val_df),
        len(test_df),
        settings.train_val_end,
        settings.test_start,
    )

    return TrainingFrame(
        train_val=train_val_df,
        test=test_df,
        feature_columns=FEATURE_COLUMNS,
        target_column="residual_db",
    )


def date_str_to_date(s: str) -> date:
    """Helper cho caller cần parse ISO date string. Pure for testability."""
    return date.fromisoformat(s)
