"""Comparison plots — Stage 1 alone vs Stage 1+2 trên test hold-out.

Sinh 2 file (must-have):
    06_rmse_per_distance.png   — RMSE theo bucket distance (0-0.5, 0.5-1, ..., 20+ km)
    07_rmse_per_sf.png         — RMSE theo spreading factor

Mục đích: trực quan hóa cải thiện của Stage 2 trên từng vùng — aggregate RMSE
giấu chi tiết, ví dụ Stage 2 cải thiện ~69% ở 0-0.5 km nhưng chỉ ~25% ở 20+ km.

Stage 1 RSSI = y_obs - residual_true (residual_true = target_column trong test).
Stage 1+2 RSSI = bundle.rssi_pred_test (no guardrail; khớp definition data_loader).
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ..data_loader import EvalBundle

log = logging.getLogger(__name__)

_DISTANCE_EDGES = [0.0, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, float("inf")]
_DISTANCE_LABELS = ["0-0.5", "0.5-1", "1-2", "2-5", "5-10", "10-20", "20+"]


def _rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def _grouped_bar(
    ax: plt.Axes,
    labels: list[str],
    rmse_stage1: list[float],
    rmse_stage12: list[float],
    counts: list[int],
) -> None:
    """Render grouped bar (Stage 1 vs Stage 1+2) + n labels above bars."""
    x = np.arange(len(labels))
    width = 0.38
    bars1 = ax.bar(
        x - width / 2, rmse_stage1, width, label="Stage 1 only", color="#cf5c36", edgecolor="black"
    )
    bars2 = ax.bar(
        x + width / 2, rmse_stage12, width, label="Stage 1 + 2", color="#4c78a8", edgecolor="black"
    )
    for bar, val in zip(bars1, rmse_stage1, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.1,
            f"{val:.1f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    for bar, val in zip(bars2, rmse_stage12, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.1,
            f"{val:.1f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    # n labels under each group
    ymax = max(max(rmse_stage1, default=0.0), max(rmse_stage12, default=0.0))
    for xi, n in zip(x, counts, strict=True):
        ax.text(
            xi,
            -0.04 * ymax,
            f"n={n}",
            ha="center",
            va="top",
            fontsize=8,
            color="gray",
        )
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")


def render(bundle: EvalBundle, out_dir: Path) -> None:
    """Render 2 comparison plots."""
    y_obs = bundle.test["rssi_dbm_measured"].to_numpy(dtype=np.float64)
    residual_true = bundle.test[bundle.target_column].to_numpy(dtype=np.float64)
    rssi_stage1 = y_obs - residual_true
    rssi_stage12 = bundle.rssi_pred_test

    # 06 — Per distance bucket
    d_km = np.power(10.0, bundle.test["log10_distance_to_serving_gw_km"].to_numpy(dtype=np.float64))
    buckets = pd.cut(d_km, bins=_DISTANCE_EDGES, labels=_DISTANCE_LABELS, include_lowest=True)
    bucket_arr = np.asarray(buckets)

    labels_used: list[str] = []
    rmse_s1: list[float] = []
    rmse_s12: list[float] = []
    counts: list[int] = []
    for lab in _DISTANCE_LABELS:
        mask = bucket_arr == lab
        n = int(mask.sum())
        if n == 0:
            continue
        labels_used.append(lab)
        rmse_s1.append(_rmse(rssi_stage1[mask], y_obs[mask]))
        rmse_s12.append(_rmse(rssi_stage12[mask], y_obs[mask]))
        counts.append(n)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    _grouped_bar(ax, labels_used, rmse_s1, rmse_s12, counts)
    ax.set_xlabel("Khoảng cách tới gateway (km)")
    ax.set_ylabel("RMSE (dB)")
    ax.set_title(
        "RMSE theo bucket distance — Stage 1 only vs Stage 1+2 (test hold-out)",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(out_dir / "06_rmse_per_distance.png", dpi=140)
    plt.close(fig)

    # 07 — Per spreading factor
    sf_arr = bundle.test["spreading_factor"].to_numpy()
    sfs = sorted(int(v) for v in np.unique(sf_arr).tolist())
    labels_sf: list[str] = []
    rmse_s1_sf: list[float] = []
    rmse_s12_sf: list[float] = []
    counts_sf: list[int] = []
    for sf in sfs:
        mask = sf_arr == sf
        n = int(mask.sum())
        if n == 0:
            continue
        labels_sf.append(f"SF{sf}")
        rmse_s1_sf.append(_rmse(rssi_stage1[mask], y_obs[mask]))
        rmse_s12_sf.append(_rmse(rssi_stage12[mask], y_obs[mask]))
        counts_sf.append(n)

    fig, ax = plt.subplots(figsize=(9, 5.5))
    _grouped_bar(ax, labels_sf, rmse_s1_sf, rmse_s12_sf, counts_sf)
    ax.set_xlabel("Spreading factor")
    ax.set_ylabel("RMSE (dB)")
    ax.set_title(
        "RMSE theo spreading factor — Stage 1 only vs Stage 1+2 (test hold-out)",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(out_dir / "07_rmse_per_sf.png", dpi=140)
    plt.close(fig)

    log.info("Comparison plots saved → %s", out_dir)
