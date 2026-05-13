"""Regression evaluation plots — đánh giá trực tiếp output Stage 2.

Sinh 2 file (must-have):
    01_scatter_rssi.png       — predicted vs actual RSSI tổng hợp (Stage 1 + 2)
    02_residual_plot.png      — error vs predicted (kiểm tra bias theo dải RSSI)
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from ..data_loader import EvalBundle

log = logging.getLogger(__name__)


def render(bundle: EvalBundle, out_dir: Path) -> None:
    """Render 2 regression plots → out_dir."""
    y_true_rssi = bundle.test["rssi_dbm_measured"].to_numpy()
    y_pred_rssi = bundle.rssi_pred_test
    error = y_true_rssi - y_pred_rssi

    # 01 — Scatter actual vs predicted RSSI
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(y_true_rssi, y_pred_rssi, alpha=0.4, s=14, edgecolors="none")
    lo = float(min(y_true_rssi.min(), y_pred_rssi.min()))
    hi = float(max(y_true_rssi.max(), y_pred_rssi.max()))
    ax.plot([lo, hi], [lo, hi], "r--", linewidth=1.0, label="y = x")
    rmse = float(np.sqrt(np.mean(error**2)))
    mae = float(np.mean(np.abs(error)))
    bias = float(np.mean(y_pred_rssi - y_true_rssi))
    ax.text(
        0.04,
        0.96,
        f"RMSE = {rmse:.2f} dBm\nMAE  = {mae:.2f} dBm\nBias = {bias:+.2f} dBm\nN    = {len(y_true_rssi)}",
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontfamily="monospace",
        fontsize=9,
        bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.85},
    )
    ax.set_xlabel("Actual (dBm)")
    ax.set_ylabel("Predicted (dBm)")
    ax.set_title("RSSI (Stage 1 + 2): actual vs predicted")
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "01_scatter_rssi.png", dpi=140)
    plt.close(fig)

    # 02 — Residual plot (error vs predicted) — kiểm tra bias theo dải
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(y_pred_rssi, error, alpha=0.4, s=14, edgecolors="none")
    ax.axhline(0, color="red", linewidth=1.0, linestyle="--")
    ax.set_xlabel("Predicted RSSI (dBm)")
    ax.set_ylabel("Error = actual − predicted (dB)")
    ax.set_title("Residual plot — kiểm tra bias theo dải RSSI")
    ax.grid(True, alpha=0.3)
    bins = np.linspace(y_pred_rssi.min(), y_pred_rssi.max(), 12)
    bin_idx = np.digitize(y_pred_rssi, bins)
    bin_means = [
        error[bin_idx == i].mean() if (bin_idx == i).any() else np.nan for i in range(1, len(bins))
    ]
    bin_centers = (bins[:-1] + bins[1:]) / 2
    ax.plot(
        bin_centers,
        bin_means,
        color="darkorange",
        linewidth=2,
        marker="o",
        label="Mean error / bin",
    )
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_dir / "02_residual_plot.png", dpi=140)
    plt.close(fig)

    log.info("Regression plots saved → %s", out_dir)
