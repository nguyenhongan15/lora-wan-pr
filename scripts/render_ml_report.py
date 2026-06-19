"""Render bao cao danh gia mo hinh ML sau khi train_extra_trees.py xong.

Goi tu Celery task `retrain_ml_model` qua subprocess. Sinh:
  - 5 plots PNG (train + hold-out)
  - summary.json (metric machine-readable)
  - summary.html (template Jinja2)
  - report.pdf (WeasyPrint render HTML)

Hold-out eval doc tu file JSON (scripts/eval_extra_trees_holdout.py viet truoc do)
qua arg --holdout-json. File missing → bao cao chi co training metrics.
Val metrics doc tu MODEL_DIR/val_metrics.json (train_extra_trees.py ghi).

Usage:
    python scripts/render_ml_report.py \
        --out-dir reports/retrain-<job_id> \
        --job-id <uuid> \
        --triggered-at "2026-06-13T03:42:00Z" \
        --triggered-by "admin@example.com" \
        --holdout-json reports/retrain-<job_id>/holdout_eval.json

Exit codes:
    0  success (du fail hold-out van 0 — bao cao van render duoc)
    1  fatal (model artifact missing / cannot read training CSV / template fail)
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import math
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
TRAIN_CSV_PATH = (
    REPO_ROOT
    / "services"
    / "ml-service"
    / "reference_wireless"
    / "data"
    / "processed"
    / "devices_history_full.csv"
)
MODEL_PATH = REPO_ROOT / "services" / "ml-service" / "data" / "extra_trees_model.joblib"
VAL_METRICS_PATH = MODEL_PATH.parent / "val_metrics.json"
TEMPLATE_PATH = Path(__file__).parent / "templates" / "ml_report.html.j2"

NUMERIC_FEATURES = [
    "frequency",
    "spreading_factor",
    "log_distance",
    "log_distance_3d",
    "delta_lat",
    "delta_lon",
    "angle",
    "gw_elevation",
    "delta_elevation",
    "elevation_angle",
    "slope",
    "roughness",
    "terrain_mean",
    "terrain_std",
    "terrain_min",
    "terrain_max",
    "fresnel_obstruction_ratio",
    "min_fresnel_clearance",
    "mean_fresnel_clearance",
    "residential_ratio",
]
ALL_FEATURES = [*NUMERIC_FEATURES, "gateway"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("render_ml_report")


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = y_true - y_pred
    ss_total = float(np.sum((y_true - y_true.mean()) ** 2))
    return {
        "n": len(err),
        "rmse_db": float(np.sqrt(np.mean(err**2))),
        "mae_db": float(np.mean(np.abs(err))),
        "bias_db": float(np.mean(err)),
        "r2": float(1 - np.sum(err**2) / ss_total) if ss_total > 0 else None,
    }


def _setup_matplotlib():
    """Force Agg backend (no display) — chay trong container khong co X.

    Force DejaVu Sans cho font.family — chua Vietnamese glyphs (ố, ầ, ặ, ỗ).
    matplotlib bundle DejaVu Sans nen luon co san, khong phu thuoc font OS.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def _plot_train_scatter(out: Path, y_true: np.ndarray, y_pred: np.ndarray) -> None:
    plt = _setup_matplotlib()
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(y_true, y_pred, alpha=0.3, s=8, c="#1f77b4")
    lo, hi = float(min(y_true.min(), y_pred.min())), float(max(y_true.max(), y_pred.max()))
    ax.plot([lo, hi], [lo, hi], "k--", alpha=0.5, label="y=x (lý tưởng)")
    ax.set_xlabel("RSSI đo được (dBm)")
    ax.set_ylabel("RSSI dự đoán (dBm)")
    ax.set_title(f"Dự đoán vs đo được (training, n={len(y_true)})")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def _plot_error_vs_distance(out: Path, dist_km: np.ndarray, err: np.ndarray) -> None:
    plt = _setup_matplotlib()
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(dist_km, err, alpha=0.3, s=8, c="#ff7f0e")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Khoảng cách (km)")
    ax.set_ylabel("Sai số = đo được − dự đoán (dB)")
    ax.set_title("Sai số theo khoảng cách")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def _plot_feature_importance(out: Path, names: list[str], importances: np.ndarray) -> None:
    plt = _setup_matplotlib()
    order = np.argsort(importances)[::-1][:20]
    fig, ax = plt.subplots(figsize=(8, 6))
    y_pos = np.arange(len(order))
    ax.barh(y_pos, importances[order], color="#2ca02c")
    ax.set_yticks(y_pos)
    ax.set_yticklabels([names[i] for i in order])
    ax.invert_yaxis()
    ax.set_xlabel("Độ quan trọng (normalized)")
    ax.set_title("Độ quan trọng của đặc trưng (top 20)")
    ax.grid(True, alpha=0.3, axis="x")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def _plot_holdout_per_bin(out: Path, bins: list[dict]) -> None:
    plt = _setup_matplotlib()
    fig, ax = plt.subplots(figsize=(9, 5))
    labels = [b["bin_km"] + " km" for b in bins]
    rmse = [b["rmse_db"] for b in bins]
    colors = ["#1a3a72" for _ in rmse]
    bars = ax.bar(labels, rmse, color=colors)
    for bar, b in zip(bars, bins, strict=False):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.2,
            f"n={b['n']}",
            ha="center",
            fontsize=9,
        )
    ax.set_ylabel("RMSE (dB)")
    ax.set_title("RMSE hold-out theo khoảng cách")
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def _plot_holdout_per_gateway(out: Path, gws: list[dict]) -> None:
    plt = _setup_matplotlib()
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = [g["gateway"][-8:] for g in gws]  # cuối gateway code cho ngắn
    rmse = [g["rmse_db"] for g in gws]
    colors = ["#1a3a72" for _ in rmse]
    bars = ax.bar(labels, rmse, color=colors)
    for bar, g in zip(bars, gws, strict=False):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.2,
            f"n={g['n']}",
            ha="center",
            fontsize=9,
        )
    ax.set_ylabel("RMSE (dB)")
    ax.set_xlabel("Gateway (8 ký tự cuối)")
    ax.set_title("RMSE hold-out theo gateway")
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def _read_holdout_json(path: Path) -> dict | None:
    """Doc holdout_eval.json (do eval_extra_trees_holdout.py viet truoc). Khong fail-hard."""
    if not path.exists():
        log.warning("Hold-out JSON missing: %s — bao cao se khong co phan hold-out", path)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Khong doc duoc holdout JSON %s: %s", path, exc)
        return None
    if not isinstance(data, dict) or "overall" not in data:
        log.warning("Holdout JSON %s thieu key 'overall'", path)
        return None
    return data


def _read_val_json(path: Path) -> dict | None:
    """Doc val_metrics.json do train_extra_trees.py viet (rmse/mae/r2/n)."""
    if not path.exists():
        log.warning("Val metrics JSON missing: %s", path)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Khong doc duoc val JSON %s: %s", path, exc)
        return None
    if not isinstance(data, dict) or data.get("n", 0) == 0:
        return None
    return data


def _summary_conclusion(holdout: dict | None) -> dict:
    """Trạng thái báo cáo: đã đánh giá hold-out hay chưa."""
    if not holdout or holdout.get("skipped"):
        return {
            "status": "CHUA_DANH_GIA",
            "label": "Chưa đánh giá hold-out",
            "reason": holdout.get("reason") if holdout else "Hold-out chưa chạy",
            "color": "gray",
        }
    rmse = holdout["overall"]["rmse_db"]
    n = holdout["overall"].get("n", 0)
    return {
        "status": "DA_DANH_GIA",
        "label": f"Đã đánh giá trên tập kiểm thử: RMSE {rmse:.2f} dB (n={n})",
        "reason": None,
        "color": "green",
    }


def _load_previous_holdout(out_dir: Path) -> dict | None:
    """Tim bao cao lan truoc gan nhat (sap xep theo mtime, bo qua chinh out_dir)."""
    parent = out_dir.parent
    if not parent.exists():
        return None
    candidates = []
    for d in parent.iterdir():
        if not d.is_dir() or d == out_dir:
            continue
        f = d / "holdout_eval.json"
        if f.exists():
            candidates.append((f.stat().st_mtime, f))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    try:
        return json.loads(candidates[0][1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _cleanup_old_reports(out_dir: Path, keep: int = 10) -> int:
    """Giu N folder bao cao gan nhat, xoa cu hon. Tra so folder bi xoa."""
    parent = out_dir.parent
    if not parent.exists():
        return 0
    folders = [d for d in parent.iterdir() if d.is_dir() and d.name.startswith("retrain-")]
    if len(folders) <= keep:
        return 0
    folders.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    deleted = 0
    for d in folders[keep:]:
        try:
            import shutil

            shutil.rmtree(d)
            deleted += 1
            log.info("Cleaned old report: %s", d.name)
        except OSError as exc:
            log.warning("Cleanup fail %s: %s", d, exc)
    return deleted


def _render_html(context: dict, out: Path) -> None:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_PATH.parent),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["fmt2"] = lambda v: (
        f"{v:.2f}" if isinstance(v, (int, float)) and not math.isnan(v) else "—"
    )
    env.filters["fmt2_signed"] = lambda v: (
        f"{v:+.2f}" if isinstance(v, (int, float)) and not math.isnan(v) else "—"
    )
    template = env.get_template(TEMPLATE_PATH.name)
    html = template.render(**context)
    out.write_text(html, encoding="utf-8")


def _render_pdf(html_path: Path, pdf_path: Path) -> str | None:
    """Tra None neu thanh cong, str loi neu fail (fail-soft).

    base_url = thu muc cua HTML → WeasyPrint resolve `assets/xxx.png` ra file
    that trong out_dir/assets/.
    """
    try:
        from weasyprint import HTML

        HTML(filename=str(html_path), base_url=str(html_path.parent)).write_pdf(str(pdf_path))
        return None
    except Exception as exc:
        log.warning("PDF render fail: %s", exc)
        return str(exc)


def render_failure_report(out_dir: Path, job_meta: dict, error_text: str) -> None:
    """Mini-report cho job failed — chi summary.html voi loi va metadata."""
    out_dir.mkdir(parents=True, exist_ok=True)
    context = {
        "job_meta": job_meta,
        "failure": {"error_text": error_text},
        "conclusion": {
            "status": "THAT_BAI",
            "label": "Huấn luyện thất bại",
            "reason": "Xem chi tiết lỗi bên dưới.",
            "color": "red",
        },
        "training": None,
        "dataset": None,
        "val": None,
        "holdout": None,
        "previous_holdout": None,
        "plots": [],
    }
    summary_path = out_dir / "summary.html"
    _render_html(context, summary_path)
    pdf_err = _render_pdf(summary_path, out_dir / "report.pdf")
    (out_dir / "summary.json").write_text(
        json.dumps(
            {
                "job_meta": job_meta,
                "status": "failed",
                "error_text": error_text,
                "pdf_error": pdf_err,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", required=True)
    p.add_argument("--job-id", required=True)
    p.add_argument("--triggered-at", required=True, help="ISO 8601")
    p.add_argument("--triggered-by", default="(unknown)")
    p.add_argument("--keep-reports", type=int, default=10)
    p.add_argument(
        "--holdout-json",
        default=None,
        help="Path den holdout_eval.json (default: <out-dir>/holdout_eval.json)",
    )
    p.add_argument(
        "--val-metrics-json",
        default=str(VAL_METRICS_PATH),
        help="Path den val_metrics.json (default: services/ml-service/data/val_metrics.json)",
    )
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    holdout_path = Path(args.holdout_json) if args.holdout_json else out_dir / "holdout_eval.json"
    val_path = Path(args.val_metrics_json)

    job_meta = {
        "job_id": args.job_id,
        "triggered_at": args.triggered_at,
        "triggered_by": args.triggered_by,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    # 1. Load model + training data
    if not MODEL_PATH.exists():
        log.error("Model artifact missing: %s", MODEL_PATH)
        return 1
    if not TRAIN_CSV_PATH.exists():
        log.error("Training CSV missing: %s", TRAIN_CSV_PATH)
        return 1

    log.info("Loading model + training CSV")
    model = joblib.load(MODEL_PATH)
    df_train = pd.read_csv(TRAIN_CSV_PATH)

    X_train = df_train[ALL_FEATURES]  # noqa: N806
    y_train = df_train["rssi"].to_numpy()
    log.info("Predicting on training set (n=%d)", len(df_train))
    y_pred_train = model.predict(X_train)
    train_metrics = _metrics(y_train, y_pred_train)

    # SF + GW + distance stats
    dataset_stats = {
        "n_rows": len(df_train),
        "n_gateways": int(df_train["gateway"].nunique()),
        "sf_distribution": {
            int(k): int(v) for k, v in df_train["spreading_factor"].value_counts().to_dict().items()
        },
        "distance_km": {
            "min": float(df_train["distance"].min() / 1000),
            "p25": float(df_train["distance"].quantile(0.25) / 1000),
            "p50": float(df_train["distance"].quantile(0.50) / 1000),
            "p75": float(df_train["distance"].quantile(0.75) / 1000),
            "max": float(df_train["distance"].max() / 1000),
        },
    }

    # 2. Plots train (luu vao assets/ cho template img src=assets/<filename>)
    log.info("Render training plots")
    _plot_train_scatter(assets_dir / "01_train_pred_vs_meas.png", y_train, y_pred_train)
    err_train = y_train - y_pred_train
    dist_km_train = df_train["distance"].to_numpy() / 1000.0
    _plot_error_vs_distance(assets_dir / "02_train_error_vs_distance.png", dist_km_train, err_train)

    # Feature importance — tu ExtraTreesRegressor sau pipeline
    et_model = model.named_steps.get("model") if hasattr(model, "named_steps") else None
    if et_model is not None and hasattr(et_model, "feature_importances_"):
        # OneHotEncoder bung gateway thanh nhieu cot — chi lay 20 numeric goc
        importances = et_model.feature_importances_
        # 20 numeric dau, sau do nhieu cot gateway one-hot — gop lai
        numeric_imp = importances[: len(NUMERIC_FEATURES)]
        gw_imp = (
            float(importances[len(NUMERIC_FEATURES) :].sum())
            if len(importances) > len(NUMERIC_FEATURES)
            else 0.0
        )
        all_names = [*NUMERIC_FEATURES, "gateway (gop)"]
        all_imp = np.concatenate([numeric_imp, [gw_imp]])
        _plot_feature_importance(assets_dir / "03_feature_importance.png", all_names, all_imp)

    # 3. Hold-out eval — doc tu file JSON do eval_extra_trees_holdout.py viet
    holdout = _read_holdout_json(holdout_path)
    val_metrics = _read_val_json(val_path)
    if holdout and holdout.get("per_distance_bin"):
        _plot_holdout_per_bin(
            assets_dir / "04_holdout_per_distance.png", holdout["per_distance_bin"]
        )
    if holdout and holdout.get("per_gateway"):
        _plot_holdout_per_gateway(assets_dir / "05_holdout_per_gateway.png", holdout["per_gateway"])

    # 4. So sanh voi lan truoc
    previous_holdout = _load_previous_holdout(out_dir)
    delta_rmse = None
    if (
        holdout
        and not holdout.get("skipped")
        and previous_holdout
        and not previous_holdout.get("skipped")
    ):
        delta_rmse = holdout["overall"]["rmse_db"] - previous_holdout["overall"]["rmse_db"]

    # 5. Render HTML + PDF
    conclusion = _summary_conclusion(holdout)

    plots = []
    for fname, title in [
        ("01_train_pred_vs_meas.png", "Dự đoán vs đo được (training)"),
        ("02_train_error_vs_distance.png", "Sai số theo khoảng cách (training)"),
        ("03_feature_importance.png", "Độ quan trọng đặc trưng"),
        ("04_holdout_per_distance.png", "Hold-out RMSE theo khoảng cách"),
        ("05_holdout_per_gateway.png", "Hold-out RMSE theo gateway"),
    ]:
        p = assets_dir / fname
        if p.exists():
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
            plots.append(
                {
                    "filename": fname,
                    "title": title,
                    "data_uri": f"data:image/png;base64,{b64}",
                }
            )

    context = {
        "job_meta": job_meta,
        "conclusion": conclusion,
        "training": {
            "metrics": train_metrics,
            "hyperparams": {
                "n_estimators": 1500,
                "max_depth": 20,
                "min_samples_split": 5,
                "min_samples_leaf": 2,
                "random_state": 42,
            },
            "features": ALL_FEATURES,
        },
        "dataset": dataset_stats,
        "val": val_metrics,
        "holdout": holdout,
        "previous_holdout": previous_holdout,
        "delta_rmse_vs_previous": delta_rmse,
        "plots": plots,
        "failure": None,
    }

    summary_path = out_dir / "summary.html"
    _render_html(context, summary_path)
    pdf_err = _render_pdf(summary_path, out_dir / "report.pdf")

    summary_json = {
        "job_meta": job_meta,
        "training": context["training"]["metrics"],
        "val": val_metrics,
        "holdout": holdout,
        "conclusion": conclusion,
        "delta_rmse_vs_previous": delta_rmse,
        "pdf_error": pdf_err,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary_json, indent=2), encoding="utf-8")

    # 6. Cleanup
    deleted = _cleanup_old_reports(out_dir, keep=args.keep_reports)
    log.info("Done. Report: %s (deleted %d old)", out_dir, deleted)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
