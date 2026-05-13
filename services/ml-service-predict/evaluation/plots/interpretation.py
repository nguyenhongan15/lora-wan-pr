"""Interpretation plot — SHAP beeswarm.

Sinh 1 file (must-have):
    05_shap_summary.png       — direction x magnitude per sample

Performance: SHAP TreeExplainer fast trên LightGBM. Toàn bộ test set (~337 row)
dùng được ngay, không cần subsample.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import shap

from ..data_loader import EvalBundle

log = logging.getLogger(__name__)


def render(bundle: EvalBundle, out_dir: Path) -> None:
    """Render SHAP summary plot."""
    feature_names = list(bundle.feature_columns)
    categorical_features = list(bundle.meta.get("categorical_features", []))
    category_maps: dict[str, list[str]] = bundle.meta.get("category_maps", {})
    x_test = bundle.test[feature_names].copy()
    for col in categorical_features:
        cats = category_maps.get(col)
        if cats is None:
            continue
        x_test[col] = pd.Categorical(x_test[col].astype(str), categories=cats)

    log.info("Computing SHAP values for %d test samples", len(x_test))
    explainer = shap.TreeExplainer(bundle.booster)
    shap_values = explainer.shap_values(x_test)

    fig = plt.figure(figsize=(10, 7))
    shap.summary_plot(
        shap_values,
        x_test,
        feature_names=feature_names,
        show=False,
        plot_size=None,
    )
    fig.suptitle("SHAP summary (beeswarm) — direction × magnitude per sample", fontsize=12)
    fig.tight_layout()
    fig.savefig(out_dir / "05_shap_summary.png", dpi=140, bbox_inches="tight")
    plt.close(fig)

    log.info("Interpretation plot saved → %s", out_dir)
