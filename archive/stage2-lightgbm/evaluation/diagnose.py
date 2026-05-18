"""Diagnostic CLI cho Stage 2 — tìm nguyên nhân test RMSE >> CV RMSE.

Khi nào dùng:
    Stage 2 CV mean ~4.58 dB nhưng test ~12.29 dB (3x gap) → cần biết:
      - Test distribution có drift khỏi train không?
      - Outliers tập trung ở dải nào (SF, distance, time, region)?
      - Top-K worst-error samples có pattern gì chung?

Usage:
    uv run python -m evaluation.diagnose --version stage2-20260513T131351Z

Output: evaluation/reports/<version>/
    diagnose_distribution.png   — histograms train vs test cho 4 feature chính
    diagnose_buckets.png        — bar chart test RMSE theo SF + distance bucket
    diagnose.txt                — text report: stats + per-bucket RMSE + top outliers
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .data_loader import load_eval_bundle

log = logging.getLogger(__name__)


def _rmse(err: np.ndarray) -> float:
    return float(np.sqrt(np.mean(err**2)))


def _bucket_rmse(df: pd.DataFrame, err: np.ndarray, col: str, bins=None) -> pd.DataFrame:
    """Group by col (categorical hoặc binned) → (n, rmse, mae, bias)."""
    if bins is not None:
        groups = pd.cut(df[col], bins=bins, include_lowest=True)
    else:
        groups = df[col]
    out = []
    for key, idx in df.groupby(groups, observed=True).groups.items():
        e = err[idx.to_numpy() - df.index[0]] if df.index[0] != 0 else err[idx.to_numpy()]
        # Safer: positional index
        positional = df.index.get_indexer(idx)
        e = err[positional]
        out.append(
            {
                "bucket": str(key),
                "n": len(e),
                "rmse": _rmse(e),
                "mae": float(np.mean(np.abs(e))),
                "bias": float(np.mean(e)),
            }
        )
    return pd.DataFrame(out).sort_values("bucket")


def _plot_distribution(train_df: pd.DataFrame, test_df: pd.DataFrame, out_path: Path) -> None:
    """4-panel: hist train vs test cho rssi, distance, SF, residual."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    panels = [
        ("rssi_dbm_measured", "RSSI measured (dBm)", axes[0, 0]),
        ("log10_distance_to_serving_gw_km", "log10(distance to GW, km)", axes[0, 1]),
        ("spreading_factor", "Spreading Factor", axes[1, 0]),
        ("residual_db", "Residual = measured − Stage1 (dB)", axes[1, 1]),
    ]
    for col, label, ax in panels:
        ax.hist(
            train_df[col],
            bins=30,
            alpha=0.55,
            label=f"train+val (n={len(train_df)})",
            color="steelblue",
            density=True,
        )
        ax.hist(
            test_df[col],
            bins=30,
            alpha=0.55,
            label=f"test (n={len(test_df)})",
            color="darkorange",
            density=True,
        )
        ax.set_xlabel(label)
        ax.set_ylabel("Density")
        ax.set_title(label)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
    fig.suptitle("Distribution drift train+val vs test", fontsize=13)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def _plot_buckets(by_sf: pd.DataFrame, by_dist: pd.DataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    ax = axes[0]
    bars = ax.bar(by_sf["bucket"].astype(str), by_sf["rmse"], color="steelblue", edgecolor="black")
    for bar, row in zip(bars, by_sf.itertuples(), strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.1,
            f"n={row.n}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    ax.set_xlabel("Spreading Factor")
    ax.set_ylabel("Test RMSE (dB)")
    ax.set_title("Test RMSE per SF")
    ax.grid(True, alpha=0.3, axis="y")

    ax = axes[1]
    bars = ax.bar(by_dist["bucket"], by_dist["rmse"], color="darkorange", edgecolor="black")
    for bar, row in zip(bars, by_dist.itertuples(), strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.1,
            f"n={row.n}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    ax.set_xlabel("Distance to serving GW (km)")
    ax.set_ylabel("Test RMSE (dB)")
    ax.set_title("Test RMSE per distance bucket")
    ax.tick_params(axis="x", rotation=20)
    ax.grid(True, alpha=0.3, axis="y")

    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def _write_report(
    out_path: Path,
    bundle,
    error: np.ndarray,
    by_sf: pd.DataFrame,
    by_dist: pd.DataFrame,
    by_week: pd.DataFrame,
    top_outliers: pd.DataFrame,
) -> None:
    train_df, test_df = bundle.train_val, bundle.test
    lines = [
        f"Stage 2 diagnostic — {bundle.model_version}",
        "=" * 70,
        "",
        f"Train+val: n={len(train_df)}, Test: n={len(test_df)}",
        f"Test RMSE: {_rmse(error):.3f} dB (artifact meta: "
        f"{bundle.meta['metrics']['test_rmse']:.3f} dB — khớp nếu data chưa drift)",
        "",
        "1. DISTRIBUTION COMPARE — train vs test",
        "-" * 70,
    ]
    cols = [
        "rssi_dbm_measured",
        "log10_distance_to_serving_gw_km",
        "spreading_factor",
        "residual_db",
        "elevation_diff_m",
    ]
    for col in cols:
        tr = train_df[col]
        te = test_df[col]
        lines.append(
            f"  {col:40s}: train μ={tr.mean():7.2f} σ={tr.std():6.2f}  "
            f"test μ={te.mean():7.2f} σ={te.std():6.2f}  "
            f"Δμ={te.mean() - tr.mean():+.2f}"
        )

    lines.extend(
        [
            "",
            "2. TEST RMSE PER SF",
            "-" * 70,
            by_sf.to_string(index=False),
            "",
            "3. TEST RMSE PER DISTANCE BUCKET",
            "-" * 70,
            by_dist.to_string(index=False),
            "",
            "4. TEST RMSE PER WEEK (Jan-Feb 2026)",
            "-" * 70,
            by_week.to_string(index=False),
            "",
            "5. TOP-15 WORST-ERROR TEST SAMPLES",
            "-" * 70,
            top_outliers.to_string(index=False),
            "",
        ]
    )
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out_dir = args.out or Path("evaluation/reports") / args.version
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = load_eval_bundle(args.version)
    test = bundle.test.reset_index(drop=True)
    y_true_rssi = test["rssi_dbm_measured"].to_numpy()
    y_pred_rssi = bundle.rssi_pred_test
    error = y_true_rssi - y_pred_rssi
    log.info("Test RMSE recomputed: %.3f dB", _rmse(error))

    # Distribution chart
    _plot_distribution(bundle.train_val, test, out_dir / "diagnose_distribution.png")

    # Bucketed RMSE
    by_sf = _bucket_rmse(test, error, "spreading_factor")
    # distance: linear km, convert from log10
    dist_km = 10 ** test["log10_distance_to_serving_gw_km"].to_numpy()
    test_with_dist = test.assign(dist_km=dist_km)
    dist_bins = [0, 1, 3, 5, 10, 20, 50, 200]
    by_dist = _bucket_rmse(test_with_dist, error, "dist_km", bins=dist_bins)

    # Per-week
    test_with_week = test.assign(week=test["timestamp"].dt.isocalendar().week.astype(int))
    by_week = _bucket_rmse(test_with_week, error, "week")

    _plot_buckets(by_sf, by_dist, out_dir / "diagnose_buckets.png")

    # Top outliers
    test_with_err = test.assign(error_db=error, abs_error=np.abs(error)).sort_values(
        "abs_error", ascending=False
    )
    cols_show = [
        "timestamp",
        "lat",
        "lon",
        "rssi_dbm_measured",
        "spreading_factor",
        "log10_distance_to_serving_gw_km",
        "residual_db",
        "error_db",
    ]
    top_outliers = test_with_err[cols_show].head(15).reset_index(drop=True)

    _write_report(out_dir / "diagnose.txt", bundle, error, by_sf, by_dist, by_week, top_outliers)
    log.info("Diagnostic saved → %s", out_dir.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
