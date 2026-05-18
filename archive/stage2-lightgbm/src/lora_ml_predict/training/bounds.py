"""Compute feature bounds cho OOD detection tại serving time.

What:
  compute_feature_bounds(train_df, feature_cols, categorical_cols, quantile_clip)
    → dict {col: {min, max} | {values}}.
Hidden:
  Quantile clip [q, 1-q] cho numeric (robust min/max),
  unique set cho categorical.
Failure mode:
  Empty df → ValueError.
  NaN trong feature → bị bỏ qua khi compute quantile.

Lý do quantile thay raw min/max:
  Raw min/max nhạy outlier — 1 sample lỗi tạo bound rộng vô lý → OOD detector
  cho phép sample lỗi tương tự nữa. Quantile [0.005, 0.995] (default) clip
  bottom 0.5% + top 0.5%, vẫn cover 99% training distribution.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


_DEFAULT_QUANTILE_CLIP = 0.005


def compute_feature_bounds(
    train_df: pd.DataFrame,
    feature_cols: Sequence[str],
    categorical_cols: Sequence[str] = ("spreading_factor",),
    quantile_clip: float = _DEFAULT_QUANTILE_CLIP,
) -> dict[str, dict[str, Any]]:
    """Sinh bounds dict cho serving OODDetector.

    Output schema cho meta.json:
        {
          "log10_distance_to_serving_gw_km": {"min": -3.0, "max": 1.6},
          "spreading_factor":                {"values": [7, 10, 12]},
          ...
        }

    Args:
        train_df: training split (KHÔNG bao gồm test → tránh leak bounds).
        feature_cols: tất cả feature columns.
        categorical_cols: subset của feature_cols treat as categorical (unique set).
        quantile_clip: q ∈ [0, 0.5). Bound = [q, 1-q] quantile.

    Returns:
        dict {col_name: {"min": float, "max": float} | {"values": list}}.
    """
    if train_df.empty:
        msg = "Cannot compute bounds on empty DataFrame"
        raise ValueError(msg)
    if not 0.0 <= quantile_clip < 0.5:
        msg = f"quantile_clip must ∈ [0, 0.5); got {quantile_clip}"
        raise ValueError(msg)

    cat_set = set(categorical_cols)
    bounds: dict[str, dict[str, Any]] = {}
    q_low, q_high = quantile_clip, 1.0 - quantile_clip

    for col in feature_cols:
        if col not in train_df.columns:
            log.warning("Column %s missing in train_df — skip bounds", col)
            continue
        series = train_df[col].dropna()
        if series.empty:
            log.warning("Column %s all NaN — skip bounds", col)
            continue

        if col in cat_set:
            uniques = sorted(series.unique().tolist())
            # Cast numpy scalar → Python native cho JSON serializable.
            normalized = [_to_native(v) for v in uniques]
            bounds[col] = {"values": normalized}
        else:
            lo = float(series.quantile(q_low))
            hi = float(series.quantile(q_high))
            bounds[col] = {"min": lo, "max": hi}

    log.info(
        "Computed bounds for %d/%d columns (quantile_clip=%g)",
        len(bounds),
        len(feature_cols),
        quantile_clip,
    )
    return bounds


def _to_native(v: Any) -> Any:
    """Convert numpy scalar → Python native (int/float/str)."""
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v
