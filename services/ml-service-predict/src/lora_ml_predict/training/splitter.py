"""Spatial grid stratified hold-out splitter.

What:
  SpatialStratifiedSplitter.assign(df) → Series['train' | 'test'] per row.
Hidden:
  Grid 0.025° cell binning, region detection (DN / HP / HD / other), per-cell
  stratification label (region x sf_mode x month_mode), sklearn
  StratifiedGroupKFold pick fold 0 = test.
Failure mode:
  KHÔNG raise per call. Cell trong stratum < 2 → log warning, fallback
  GroupKFold không stratify cho stratum đó.

Lý do thay time-split (Nov-Dec → Jan-Feb):
  Test set cũ skew nặng (100% SF12, 82% < 1km) vì survey protocol đổi.
  Spatial cell hold-out đảm bảo: (a) distribution match (stratified), (b) no
  location leak (1 cell chỉ 1 split). Đo spatial generalization sang vùng
  chưa khảo sát — phù hợp triết lý continuous learning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

log = logging.getLogger(__name__)


# Grid 0.01° ≈ 1.1 km. Khớp với spatial_cv.py để consistent (1 cell = 1 group
# cho cả train/test split và k-fold trong train).
#
# Tại sao 0.01° (giảm từ 0.025° = 2.5 km):
#   Smoke run đầu (DN data 9553 rows, cell 0.025°) chỉ sinh 34 cell. Khi
#   StratifiedGroupKFold n_splits=5, mỗi fold ~7 cell. Nếu fold-0 trúng 11
#   cell mật độ cao → test_fraction_actual = 0.65 thay vì 0.20.
#   Giảm cell xuống 0.01° → ~100-150 cell trên cùng bbox, fold đều ~20 cell
#   mỗi fold, test_fraction sát 0.20 hơn. Trade-off: cell adjacent có thể
#   leak spatial autocorrelation, nhưng LoRa correlation length ~ 500 m nên
#   1.1 km cell vẫn an toàn.
_DEFAULT_CELL_SIZE_DEG = 0.01

# n_splits = 1/test_fraction. 0.2 → 5 fold, pick fold 0 = 20% test.
_DEFAULT_TEST_FRACTION = 0.2

# Region bbox cho stratify. Theo memory scope_vietnam_only + stage1 DN scope.
# "other" = tất cả ngoài 2 vùng chính → bucket riêng để stratify không bỏ sót.
_REGION_BBOX: dict[str, tuple[float, float, float, float]] = {
    "da_nang": (15.8, 16.3, 107.9, 108.5),
    "hai_phong": (20.6, 21.1, 106.4, 107.0),
    "hai_duong": (20.7, 20.95, 106.0, 106.4),
}


@dataclass(frozen=True, slots=True)
class SplitReport:
    """Output thống kê 1 split để log + lưu meta.json."""

    n_train: int
    n_test: int
    n_train_cells: int
    n_test_cells: int
    test_fraction_actual: float


def _detect_region(lat: float, lon: float) -> str:
    """Trả region name dựa trên bbox check. 'other' nếu không match."""
    for name, (min_lat, max_lat, min_lon, max_lon) in _REGION_BBOX.items():
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return name
    return "other"


def _cell_id(lat: float, lon: float, cell_size: float) -> str:
    """Quantize (lat, lon) → string cell id. String thay int để debug dễ đọc."""
    row = int(lat / cell_size)
    col = int(lon / cell_size)
    return f"{row}_{col}"


def _stratum_label(
    cell_rows: pd.DataFrame,
    sf_col: str,
    timestamp_col: str,
) -> str:
    """Một label string per cell, encode (region, sf_mode, month_mode).

    Mode = giá trị xuất hiện nhiều nhất trong cell. Cell có nhiều SF/month
    chia về mode duy nhất → label categorical đơn giản cho StratifiedGroupKFold.
    """
    region = cell_rows["__region"].iloc[0]
    sf_mode = int(cell_rows[sf_col].mode().iloc[0])
    month_mode = int(cell_rows[timestamp_col].dt.month.mode().iloc[0])
    return f"{region}|sf{sf_mode}|m{month_mode}"


class SpatialStratifiedSplitter:
    """Stratified spatial hold-out splitter — train vs test theo grid cell.

    Interface:
        splitter = SpatialStratifiedSplitter(seed=42)
        labels = splitter.assign(df)   # Series['train' | 'test'], same index

    Hidden:
        - Grid cell quantize cell_size_deg.
        - Region detection from bbox lookup.
        - Per-cell stratum label = region x sf_mode x month_mode.
        - StratifiedGroupKFold(n_splits=5) → fold 0 = test.
        - Edge case: stratum có < 2 cell → drop stratify (single GroupKFold).

    Output split deterministic theo seed. KHÔNG mutate df.
    """

    def __init__(
        self,
        cell_size_deg: float = _DEFAULT_CELL_SIZE_DEG,
        test_fraction: float = _DEFAULT_TEST_FRACTION,
        seed: int = 42,
        lat_col: str = "lat",
        lon_col: str = "lon",
        sf_col: str = "spreading_factor",
        timestamp_col: str = "timestamp",
    ) -> None:
        if not 0.0 < test_fraction < 1.0:
            msg = f"test_fraction must ∈ (0, 1); got {test_fraction}"
            raise ValueError(msg)
        self._cell_size = cell_size_deg
        self._n_splits = round(1.0 / test_fraction)
        self._seed = seed
        self._lat_col = lat_col
        self._lon_col = lon_col
        self._sf_col = sf_col
        self._timestamp_col = timestamp_col
        self._last_report: SplitReport | None = None

    @property
    def last_report(self) -> SplitReport | None:
        return self._last_report

    @property
    def cell_size_deg(self) -> float:
        return self._cell_size

    def assign(self, df: pd.DataFrame) -> pd.Series:
        """Return Series['train' | 'test'] cùng index df.

        Steps:
          1. Compute cell_id + region per row.
          2. Per-cell stratum label = region|sf_mode|month_mode.
          3. StratifiedGroupKFold(n_splits=5) on cell groups + stratum labels.
          4. Fold 0 = test, các fold còn lại = train.
        """
        if df.empty:
            msg = "Cannot split empty DataFrame"
            raise ValueError(msg)

        work = df.copy()
        work["__cell_id"] = [
            _cell_id(lat, lon, self._cell_size)
            for lat, lon in zip(work[self._lat_col], work[self._lon_col], strict=True)
        ]
        work["__region"] = [
            _detect_region(lat, lon)
            for lat, lon in zip(work[self._lat_col], work[self._lon_col], strict=True)
        ]
        work[self._timestamp_col] = pd.to_datetime(work[self._timestamp_col], utc=True)

        # Per-cell stratum: dùng mode trong cell. Cell-level label cho
        # StratifiedGroupKFold (cell = group, stratum = y).
        cell_strata = (
            work.groupby("__cell_id", sort=False)
            .apply(
                lambda g: _stratum_label(g, self._sf_col, self._timestamp_col),
                include_groups=False,
            )
            .rename("__stratum")
        )
        work = work.merge(cell_strata, left_on="__cell_id", right_index=True, how="left")

        # Stratum count check — < 2 cell trong stratum thì StratifiedGroupKFold
        # raise; merge các stratum hiếm thành "other_rare" để fit được.
        stratum_cell_counts = work.groupby("__stratum")["__cell_id"].nunique()
        rare_strata = stratum_cell_counts[stratum_cell_counts < self._n_splits].index.tolist()
        if rare_strata:
            log.warning(
                "Strata with < %d unique cells merged to 'rare_bucket': %s",
                self._n_splits,
                rare_strata,
            )
            work.loc[work["__stratum"].isin(rare_strata), "__stratum"] = "rare_bucket"

        groups = work["__cell_id"].to_numpy()
        strata = work["__stratum"].to_numpy()
        dummy_x = np.zeros((len(work), 1))

        sgkf = StratifiedGroupKFold(n_splits=self._n_splits, shuffle=True, random_state=self._seed)
        train_idx_arr: np.ndarray | None = None
        test_idx_arr: np.ndarray | None = None
        for fold_id, (train_idx, test_idx) in enumerate(
            sgkf.split(dummy_x, y=strata, groups=groups)
        ):
            if fold_id == 0:
                train_idx_arr, test_idx_arr = train_idx, test_idx
                break
        if train_idx_arr is None or test_idx_arr is None:
            msg = "StratifiedGroupKFold yielded no fold — check df size vs n_splits"
            raise RuntimeError(msg)

        labels = pd.Series("train", index=df.index, dtype=object)
        labels.iloc[test_idx_arr] = "test"

        train_cells = set(work["__cell_id"].iloc[train_idx_arr])
        test_cells = set(work["__cell_id"].iloc[test_idx_arr])
        overlap = train_cells & test_cells
        if overlap:
            msg = f"Cell leakage detected: {len(overlap)} cells in both splits"
            raise RuntimeError(msg)

        self._last_report = SplitReport(
            n_train=int((labels == "train").sum()),
            n_test=int((labels == "test").sum()),
            n_train_cells=len(train_cells),
            n_test_cells=len(test_cells),
            test_fraction_actual=float((labels == "test").mean()),
        )
        log.info(
            "Split: train=%d (%d cells), test=%d (%d cells), test_frac=%.3f",
            self._last_report.n_train,
            self._last_report.n_train_cells,
            self._last_report.n_test,
            self._last_report.n_test_cells,
            self._last_report.test_fraction_actual,
        )
        return labels
