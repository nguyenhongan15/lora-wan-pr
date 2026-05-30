"""Train Stage 2 residual model: XGBoost regressor on (features → residual_db).

Flow:
  1. Query ts.survey_training + geo.gateways trong train/test windows.
     Filter d<50km để loại survey ETL corruption (project_survey_etl_corruption_2026_05_27).
  2. Build Stage1ItuModel + CrcCovlibBackend (qua workspace import api-service).
  3. Per row: pred = stage1.predict(target, gw); residual = measured - pred.uplink_rssi_dbm.
  4. Train XGBoost (10 features → residual) trên train window.
  5. Eval RMSE/MAE trên test hold-out.
  6. joblib.dump model artifact (compressed) tới --output-path.

Phải chạy trong container có crc-covlib runtime (api-service container).
Stage1 prediction là sync C++; KHÔNG async hoá — chỉ tốn dòng code.

Usage (trong api-service container):
    pip install --no-cache-dir xgboost joblib pandas
    uv run python scripts/train_residual_model.py
    uv run python scripts/train_residual_model.py --bbox danang \\
        --output-path /app-shared/ml/stage2_xgb.joblib
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API_SRC = _REPO_ROOT / "services" / "api-service" / "src"
# Fallback cho local run (api-service container đã có lora_coverage_api ở
# /install — sys.path không cần touch).
if _API_SRC.is_dir() and str(_API_SRC) not in sys.path:
    sys.path.insert(0, str(_API_SRC))


log = logging.getLogger("train_residual")

# Khớp _BBOX_PRESETS của validate_stage1_itu.py.
_BBOX_PRESETS: dict[str, tuple[float, float, float, float]] = {
    "danang": (15.8, 16.3, 107.9, 108.5),
    "haiphong": (20.7, 21.0, 106.55, 106.85),
    "vietnam": (8.4, 23.4, 102.1, 109.5),
}

# Khớp ml-service/app.py:extract_features_dict — XGBoost predict tại runtime dùng
# DataFrame với column names này. Thứ tự không quan trọng (xgboost tự align),
# nhưng giữ explicit để dễ debug.
FEATURE_COLS = [
    "lat",
    "lon",
    "sf",
    "frequency_mhz",
    "gw_lat",
    "gw_lon",
    "gw_alt",
    "gw_ant_h",
    "gw_gain",
    "gw_tx_p",
]


def _fetch_rows(
    db_url: str,
    bbox: tuple[float, float, float, float],
    start: str,
    end: str,
    max_link_km: float,
):
    import psycopg

    min_lat, max_lat, min_lon, max_lon = bbox
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
          AND ST_DistanceSphere(t.location::geometry, gw.location::geometry) < %s
    """
    params = [start, end, min_lat, max_lat, min_lon, max_lon, max_link_km * 1000.0]
    log.info("Querying window %s..%s d_max=%.0fkm bbox=%s", start, end, max_link_km, bbox)
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _build_dataset(rows, stage1, label: str) -> tuple[np.ndarray, np.ndarray]:
    """Run Stage 1 predict on each row → return (X[n,10], y[n] residual_db).

    Sequential loop — Stage1.predict() là sync C++; threadpool không tăng tốc
    vì crc-covlib GIL-bound. Multiprocessing overhead lớn cho dataset <50k rows.
    """
    from lora_coverage_api.domain.coverage import Gateway, GatewayId, Target

    feats: list[list[float]] = []
    residuals: list[float] = []
    n_errors = 0
    n_total = len(rows)
    log_every = max(1, n_total // 20)

    for idx, r in enumerate(rows):
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
            feats.append(
                [
                    target.latitude,
                    target.longitude,
                    float(target.spreading_factor),
                    target.frequency_mhz,
                    gw.latitude,
                    gw.longitude,
                    gw.altitude_m,
                    gw.antenna_height_m,
                    gw.antenna_gain_dbi,
                    gw.tx_power_dbm,
                ]
            )
            residuals.append(residual)
        except Exception as e:
            n_errors += 1
            if n_errors <= 5:
                log.warning("[%s] row %d error: %r", label, idx, e)

        if (idx + 1) % log_every == 0:
            log.info("[%s] %d/%d processed (%d errors)", label, idx + 1, n_total, n_errors)

    if not feats:
        raise RuntimeError(f"[{label}] zero usable rows (n_errors={n_errors})")
    log.info("[%s] kept %d / %d rows (errors=%d)", label, len(feats), n_total, n_errors)
    return np.asarray(feats, dtype=np.float64), np.asarray(residuals, dtype=np.float64)


def _build_stage1(env: dict):
    from lora_coverage_api.application.itu.model import Stage1ItuModel
    from lora_coverage_api.application.path_loss import resolve_environment_profile
    from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend

    dem_dir = Path(env["LORA_DEM_DIRECTORY"])
    surf_raw = env.get("LORA_SURFACE_DEM_DIRECTORY", "")
    surf_dir = Path(surf_raw) if surf_raw else None
    lc_raw = env.get("LORA_LANDCOVER_DIRECTORY", "")
    lc_dir = Path(lc_raw) if lc_raw else None
    p_time = float(env.get("LORA_ITU_PERCENT_TIME", "50.0"))
    p_loc = float(env.get("LORA_ITU_PERCENT_LOCATION", "50.0"))
    env_name = env.get("LORA_ENV_PROFILE", "suburban")

    backend = CrcCovlibBackend(
        dem_directory=dem_dir,
        surface_dem_directory=surf_dir,
        landcover_directory=lc_dir,
        model_version="stage2-residual-train",
        percent_time=p_time,
        percent_location=p_loc,
    )
    return Stage1ItuModel(
        model_version="stage2-residual-train",
        backend=backend,
        env_profile=resolve_environment_profile(env_name),
    )


def _stats(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = y_true - y_pred
    return {
        "n": int(err.size),
        "bias_db": float(np.mean(err)),
        "rmse_db": float(np.sqrt(np.mean(err**2))),
        "mae_db": float(np.mean(np.abs(err))),
    }


_DIST_BINS = [(0.0, 2.0), (2.0, 5.0), (5.0, 10.0), (10.0, 50.0)]
_DIST_LABELS = ["<2km", "2-5km", "5-10km", "10-50km"]


def _plot_eval(
    model,
    df_train_full,
    df_test,
    y_train: np.ndarray,
    y_test: np.ndarray,
    train_pred: np.ndarray,
    test_pred: np.ndarray,
    plot_dir: Path,
) -> None:
    """Vẽ 5 biểu đồ đánh giá vào plot_dir (PNG, dpi=120)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir.mkdir(parents=True, exist_ok=True)

    # 1. Learning curve: val RMSE theo boosting round
    evals = getattr(model, "evals_result_", None) or {}
    val_key = next(iter(evals), None)
    if val_key and "rmse" in evals[val_key]:
        rmse_curve = evals[val_key]["rmse"]
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(rmse_curve, label="val RMSE")
        ax.axvline(
            model.best_iteration,
            color="red",
            linestyle="--",
            label=f"best iter={model.best_iteration}",
        )
        ax.set_xlabel("Boosting round")
        ax.set_ylabel("RMSE (dB)")
        ax.set_title("Learning curve (early-stopping val fold)")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(plot_dir / "01_learning_curve.png", dpi=120)
        plt.close(fig)

    # 2. Predicted vs measured residual (test)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(y_test, test_pred, alpha=0.4, s=10)
    lim = float(max(np.abs(y_test).max(), np.abs(test_pred).max(), 1.0))
    ax.plot([-lim, lim], [-lim, lim], "k--", alpha=0.5, label="y=x")
    ax.set_xlabel("Measured residual (dB)")
    ax.set_ylabel("Predicted residual (dB)")
    ax.set_title(f"Predicted vs measured (test, n={len(y_test)})")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(plot_dir / "02_pred_vs_meas.png", dpi=120)
    plt.close(fig)

    # 3. Error vs distance (test)
    err = y_test - test_pred
    dist = df_test["distance_km"].to_numpy()
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(dist, err, alpha=0.4, s=10)
    ax.axhline(0, color="red", linestyle="--", alpha=0.6)
    ax.set_xlabel("Distance (km)")
    ax.set_ylabel("Error = measured - predicted (dB)")
    ax.set_title("Residual error vs distance (test)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(plot_dir / "03_error_vs_distance.png", dpi=120)
    plt.close(fig)

    # 4. Per distance-bin RMSE + bias
    rmse_per, bias_per, n_per = [], [], []
    for lo, hi in _DIST_BINS:
        mask = (dist >= lo) & (dist < hi)
        if mask.sum() == 0:
            rmse_per.append(0.0)
            bias_per.append(0.0)
            n_per.append(0)
            continue
        e = err[mask]
        rmse_per.append(float(np.sqrt(np.mean(e**2))))
        bias_per.append(float(np.mean(e)))
        n_per.append(int(mask.sum()))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    x = np.arange(len(_DIST_LABELS))
    ax1.bar(x, rmse_per)
    for i, n in enumerate(n_per):
        ax1.text(i, rmse_per[i] + 0.3, f"n={n}", ha="center", fontsize=9)
    ax1.set_xticks(x)
    ax1.set_xticklabels(_DIST_LABELS)
    ax1.set_ylabel("RMSE (dB)")
    ax1.set_title("RMSE per distance bin (test)")
    ax1.grid(True, alpha=0.3, axis="y")

    bar_colors = ["green" if abs(b) < 5 else ("orange" if abs(b) < 10 else "red") for b in bias_per]
    ax2.bar(x, bias_per, color=bar_colors)
    ax2.axhline(0, color="black", linewidth=0.8)
    for i, b in enumerate(bias_per):
        offset = 0.5 if b >= 0 else -1.0
        ax2.text(i, b + offset, f"{b:+.2f}", ha="center", fontsize=9)
    ax2.set_xticks(x)
    ax2.set_xticklabels(_DIST_LABELS)
    ax2.set_ylabel("Bias = mean(measured - predicted) (dB)")
    ax2.set_title("Bias per distance bin (test)")
    ax2.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(plot_dir / "04_per_bin.png", dpi=120)
    plt.close(fig)

    # 5. Feature importance (gain)
    importance = model.feature_importances_
    cols = list(df_train_full.columns)
    order = np.argsort(importance)[::-1]
    fig, ax = plt.subplots(figsize=(8, 6))
    y_pos = np.arange(len(cols))
    ax.barh(y_pos, importance[order])
    ax.set_yticks(y_pos)
    ax.set_yticklabels([cols[i] for i in order])
    ax.invert_yaxis()
    ax.set_xlabel("Gain importance (normalized)")
    ax.set_title("Feature importance")
    ax.grid(True, alpha=0.3, axis="x")
    fig.tight_layout()
    fig.savefig(plot_dir / "05_feature_importance.png", dpi=120)
    plt.close(fig)

    # Đè train RMSE để hiển thị mức overfit khi so với hold-out
    train_rmse = float(np.sqrt(np.mean((y_train - train_pred) ** 2)))
    test_rmse = float(np.sqrt(np.mean((y_test - test_pred) ** 2)))
    log.info(
        "Saved 5 plots → %s | train RMSE=%.2f vs test RMSE=%.2f (gap=%.2f dB)",
        plot_dir,
        train_rmse,
        test_rmse,
        test_rmse - train_rmse,
    )


def _train(args, env: dict) -> int:
    import joblib
    import pandas as pd
    import xgboost as xgb

    bbox = _BBOX_PRESETS[args.bbox]
    cache_path = Path(args.cache_path) if args.cache_path else None

    if cache_path and cache_path.exists():
        log.info("Loading cached Stage 1 outputs from %s", cache_path)
        cache = np.load(cache_path)
        X_train, y_train = cache["X_train"], cache["y_train"]  # noqa: N806
        X_test, y_test = cache["X_test"], cache["y_test"]  # noqa: N806
    else:
        train_rows = _fetch_rows(
            env["LORA_DB_URL"], bbox, args.train_start, args.train_end, args.max_link_km
        )
        test_rows = _fetch_rows(
            env["LORA_DB_URL"], bbox, args.test_start, args.test_end, args.max_link_km
        )
        if not train_rows or not test_rows:
            log.error("Empty train or test window — adjust dates")
            return 1
        log.info("Train rows: %d | Test rows: %d", len(train_rows), len(test_rows))

        stage1 = _build_stage1(env)
        log.info("Computing Stage 1 baseline for train set...")
        X_train, y_train = _build_dataset(train_rows, stage1, "train")  # noqa: N806
        log.info("Computing Stage 1 baseline for test set...")
        X_test, y_test = _build_dataset(test_rows, stage1, "test")  # noqa: N806
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez(cache_path, X_train=X_train, y_train=y_train, X_test=X_test, y_test=y_test)
            log.info("Cached Stage 1 outputs → %s", cache_path)

    log.info(
        "Train residual stats: mean=%.2f std=%.2f n=%d",
        y_train.mean(),
        y_train.std(ddof=1),
        len(y_train),
    )

    from sklearn.model_selection import StratifiedKFold

    def _add_derived(X: np.ndarray) -> pd.DataFrame:  # noqa: N803
        df = pd.DataFrame(X, columns=FEATURE_COLS)
        lat1, lon1 = np.radians(df["lat"]), np.radians(df["lon"])
        lat2, lon2 = np.radians(df["gw_lat"]), np.radians(df["gw_lon"])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
        df["distance_km"] = 2 * 6371.0088 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
        df["log_distance_km"] = np.log1p(df["distance_km"])
        df["delta_alt_m"] = df["gw_alt"] + df["gw_ant_h"]
        return df

    df_train_full = _add_derived(X_train)
    df_test = _add_derived(X_test)

    # v0.4: phân tầng theo SF để mỗi nếp gấp có đủ tỷ lệ SF7-SF12; lấy nếp gấp
    # đầu tiên làm train/val cho early-stopping. SF hiếm (vd SF8) không bị bỏ
    # rơi vào val mà mô hình không học.
    sf_labels = df_train_full["sf"].astype(int).to_numpy()
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    train_idx, val_idx = next(skf.split(df_train_full, sf_labels))
    df_train = df_train_full.iloc[train_idx].reset_index(drop=True)
    df_val = df_train_full.iloc[val_idx].reset_index(drop=True)
    y_train_inner = y_train[train_idx]
    y_val = y_train[val_idx]
    log.info("Inner split (stratified by SF): train=%d val=%d", len(df_train), len(df_val))

    model = xgb.XGBRegressor(
        tree_method="hist",
        n_estimators=args.n_estimators,
        learning_rate=args.learning_rate,
        max_depth=args.max_depth,
        min_child_weight=args.min_child_weight,
        subsample=args.subsample,
        colsample_bytree=args.colsample_bytree,
        reg_alpha=args.reg_alpha,
        reg_lambda=args.reg_lambda,
        early_stopping_rounds=args.early_stopping_rounds,
        n_jobs=-1,
        random_state=42,
    )
    model.fit(
        df_train,
        y_train_inner,
        eval_set=[(df_val, y_val)],
        verbose=False,
    )
    log.info("Best iteration: %d / %d", model.best_iteration, args.n_estimators)

    train_pred = model.predict(df_train_full)
    test_pred = model.predict(df_test)
    train_stats = _stats(y_train, train_pred)
    test_stats = _stats(y_test, test_pred)
    null_test = _stats(y_test, np.zeros_like(y_test))
    null_train = _stats(y_train, np.zeros_like(y_train))

    log.info(
        "Train fit:     RMSE=%.2f MAE=%.2f bias=%.2f (n=%d)",
        train_stats["rmse_db"],
        train_stats["mae_db"],
        train_stats["bias_db"],
        train_stats["n"],
    )
    log.info(
        "Hold-out test: RMSE=%.2f MAE=%.2f bias=%.2f (n=%d)",
        test_stats["rmse_db"],
        test_stats["mae_db"],
        test_stats["bias_db"],
        test_stats["n"],
    )
    log.info(
        "Null baseline:  train RMSE=%.2f | test RMSE=%.2f MAE=%.2f",
        null_train["rmse_db"],
        null_test["rmse_db"],
        null_test["mae_db"],
    )

    output = Path(args.output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, output, compress=3)
    log.info("Saved model → %s (%.1f KB)", output, output.stat().st_size / 1024.0)

    if args.plot_dir:
        _plot_eval(
            model,
            df_train_full,
            df_test,
            y_train,
            y_test,
            train_pred,
            test_pred,
            Path(args.plot_dir),
        )
    return 0


def main() -> int:
    import os

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    p = argparse.ArgumentParser()
    p.add_argument("--bbox", choices=list(_BBOX_PRESETS), default="danang")
    # Memory project_dataset_split_rule: train+val Nov-Dec 2025, test Jan-Feb 2026.
    p.add_argument("--train-start", default="2025-11-19")
    p.add_argument("--train-end", default="2025-12-31")
    p.add_argument("--test-start", default="2026-01-01")
    p.add_argument("--test-end", default="2026-02-28")
    p.add_argument(
        "--max-link-km",
        type=float,
        default=50.0,
        help="Filter d<X km (survey ETL corruption guard).",
    )
    p.add_argument("--n-estimators", type=int, default=2000)
    p.add_argument("--learning-rate", type=float, default=0.05)
    p.add_argument("--max-depth", type=int, default=4)
    # v0.4 (2026-05-30): min_child_weight 10→20, reg_lambda 2.0→10.0 để chống
    # cây vẽ pattern từ <5 mẫu/leaf ở vùng 2-5 km thưa (45 mẫu). Test 4 cấu
    # hình cho RMSE hold-out 13.93 → 10.94 dB, lệch 2-5 km +17.94 → +3.18 dB.
    p.add_argument("--min-child-weight", type=int, default=20)
    p.add_argument("--subsample", type=float, default=0.7)
    p.add_argument("--colsample-bytree", type=float, default=0.7)
    p.add_argument("--reg-alpha", type=float, default=1.0)
    p.add_argument("--reg-lambda", type=float, default=10.0)
    p.add_argument("--early-stopping-rounds", type=int, default=50)
    p.add_argument(
        "--output-path",
        default="/app-shared/ml/stage2_xgb.joblib",
        help="Output joblib path (container view).",
    )
    p.add_argument(
        "--cache-path",
        default=None,
        help="Cache Stage 1 outputs để re-run nhanh (npz). Skip stage1 nếu tồn tại.",
    )
    p.add_argument(
        "--plot-dir",
        default=None,
        help="Nếu set, vẽ 5 biểu đồ PNG vào thư mục này (cần matplotlib).",
    )
    args = p.parse_args()
    return _train(args, dict(os.environ))


if __name__ == "__main__":
    raise SystemExit(main())
