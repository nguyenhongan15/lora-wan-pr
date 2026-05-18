"""Grid-based GroupKFold cho Stage 2 spatial CV.

What:
  assign_spatial_folds(df, k) → np.ndarray fold ids in [0, k).
Hidden:
  Grid cell quantize (lat, lon) → cell_id; sklearn GroupKFold lo phần
  partition cell-group thành k fold. Fallback StratifiedGroupKFold theo
  residual quartile nếu imbalance vẫn nặng.
Failure mode:
  N < k → raise.
  Số cell < k → raise (không partition được).

Lý do thay KMeans:
  KMeans clustering trên (lat, lon) sinh fold lệch nặng khi mật độ data
  không đều (run trước: [8036, 198, 393, 179, 410] — fold 0 nuốt 87%).
  Mean CV RMSE bị skew theo fold đông, không phản ánh gen-error.

  Grid-cell GroupKFold:
    1. Quantize toạ độ về cell discrete (~2.5 km). Cell là group.
    2. GroupKFold đảm bảo mọi sample cùng cell nằm cùng fold — no leakage.
    3. K fold ≈ cân bằng số cell, không cân bằng số sample → nếu mật độ
       vẫn lệch thì check max/min sample ratio, fallback StratifiedGroupKFold.

  Cell size 0.025° ≈ 2.7 km lat x 2.4 km lon @ 16°N. Đủ lớn để chống
  spatial autocorrelation (LoRa propagation correlated < 1 km), đủ nhỏ
  để DN bbox sinh ~50-150 cell với data thực.

Plan §4.2 — Q7 spatial blocked K-fold, K=5.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold, StratifiedGroupKFold

log = logging.getLogger(__name__)

# Grid cell size theo degree. 0.01° ≈ 1.1 km lat ở 16°N. Khớp splitter.py.
# Lý do giảm từ 0.025° → 0.01°: DN data 9.5k rows / 0.025° = 34 cell → fold
# imbalance 3-10×. 0.01° sinh ~120 cell, fold sát đều hơn. LoRa propagation
# autocorrelation length ~500 m nên 1.1 km cell vẫn đủ chống leak.
_GRID_CELL_DEG = 0.01

# Ngưỡng imbalance: max_fold_size / min_fold_size. Vượt → fallback Stratified.
_IMBALANCE_THRESHOLD = 3.0

# Số bin residual cho stratify (quartile).
_RESIDUAL_STRATIFY_BINS = 4


def _cell_id(lat: float, lon: float) -> int:
    """Quantize (lat, lon) về integer cell id.

    Cantor pairing không cần — dùng tuple hash đơn giản: row*100000 + col.
    DN bbox lat ∈ [15.8, 16.3], lon ∈ [107.9, 108.5] → row, col ∈ [0, ~25].
    Đủ tách bạch, no collision.
    """
    row = int(lat / _GRID_CELL_DEG)
    col = int(lon / _GRID_CELL_DEG)
    return row * 100000 + col


def _compute_groups(df: pd.DataFrame, lat_col: str, lon_col: str) -> np.ndarray:
    return np.array(
        [_cell_id(lat, lon) for lat, lon in zip(df[lat_col], df[lon_col], strict=True)],
        dtype=np.int64,
    )


def _fold_sizes(folds: np.ndarray, k: int) -> list[int]:
    return [int((folds == i).sum()) for i in range(k)]


def _imbalance_ratio(sizes: list[int]) -> float:
    """max/min — guard min=0 (fold rỗng) ra inf."""
    mn = min(sizes)
    return float("inf") if mn == 0 else max(sizes) / mn


def assign_spatial_folds(
    df: pd.DataFrame,
    k: int = 5,
    seed: int = 42,
    lat_col: str = "lat",
    lon_col: str = "lon",
    residual_col: str = "residual_db",
) -> np.ndarray:
    """Trả fold_id (int [0, k)) cho mỗi row qua grid-cell GroupKFold.

    Try GroupKFold trước; nếu max/min fold size > _IMBALANCE_THRESHOLD và df có
    residual_col, fallback StratifiedGroupKFold (stratify theo residual quartile)
    để cân bằng cả size + distribution.

    Args:
        df: DataFrame có lat, lon (và optional residual_db cho stratify).
        k: số fold.
        seed: reproducibility cho StratifiedGroupKFold shuffle.
        lat_col, lon_col: tên cột.
        residual_col: cột target để stratify nếu fallback.

    Returns:
        np.ndarray shape (len(df),) dtype int64.

    Raises:
        ValueError: N < k hoặc số cell < k.
    """
    n = len(df)
    if n < k:
        msg = f"need ≥ {k} rows for {k}-fold; got {n}"
        raise ValueError(msg)

    groups = _compute_groups(df, lat_col, lon_col)
    n_unique = len(np.unique(groups))
    if n_unique < k:
        msg = f"need ≥ {k} grid cells for {k}-fold; got {n_unique} (try smaller cell size)"
        raise ValueError(msg)
    log.info("Grid: %d unique cells over %d rows", n_unique, n)

    # GroupKFold không cần y; partition group-set thành k.
    folds = np.empty(n, dtype=np.int64)
    gkf = GroupKFold(n_splits=k)
    # GroupKFold cần X (dummy) + groups. Output là indices.
    dummy_x = np.zeros((n, 1))
    for fold_id, (_, val_idx) in enumerate(gkf.split(dummy_x, groups=groups)):
        folds[val_idx] = fold_id

    sizes = _fold_sizes(folds, k)
    ratio = _imbalance_ratio(sizes)
    log.info("GroupKFold sizes: %s, imbalance ratio=%.2f", sizes, ratio)

    if ratio <= _IMBALANCE_THRESHOLD or residual_col not in df.columns:
        return folds

    # Fallback: StratifiedGroupKFold theo residual quartile.
    log.warning(
        "Fold imbalance %.2f > %.1f — fallback StratifiedGroupKFold on residual quartile",
        ratio,
        _IMBALANCE_THRESHOLD,
    )
    residuals = df[residual_col].to_numpy(dtype=np.float64)
    # qcut với duplicates='drop' để tránh raise khi bin edge trùng (residual tập trung).
    strata = pd.qcut(residuals, q=_RESIDUAL_STRATIFY_BINS, labels=False, duplicates="drop")
    if strata is None:
        return folds
    # qcut có thể trả NaN nếu input có NaN — drop NaN không có nghĩa cho stratify
    # nhưng residual đã được Stage 1 compute đầy đủ, nên assume non-null.
    strata_arr = np.asarray(strata, dtype=np.int64)

    sgkf = StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=seed)
    folds_stratified = np.empty(n, dtype=np.int64)
    for fold_id, (_, val_idx) in enumerate(sgkf.split(dummy_x, y=strata_arr, groups=groups)):
        folds_stratified[val_idx] = fold_id

    sizes2 = _fold_sizes(folds_stratified, k)
    log.info(
        "StratifiedGroupKFold sizes: %s, imbalance ratio=%.2f", sizes2, _imbalance_ratio(sizes2)
    )
    return folds_stratified
