"""Stage 1 drift report — bias + σ của (RSSI_measured - RSSI_stage1) trên train.

What:
  recalibrate(train_df) → Stage1RecalReport (bias_db, sigma_db, n_samples,
  recommend_review).
Hidden:
  Numpy mean/std trên cột residual_db (đã có sẵn từ data.collect()).
Failure mode:
  < 30 sample → ValueError.

Lý do report-only, KHÔNG auto-update Stage 1:
  Stage 1 dùng ITU-R P.1812 (physics first-principles) — không có hyperparameter
  để "tune" theo data. Bias chỉ phản ánh systematic offset (vd antenna gain
  config sai, DEM resolution thiếu, P.1812 percent_time chọn sai). Bias > 5 dB
  hoặc σ > 12 dB là tín hiệu cho ops review, không tự sửa.

Khi nào gọi:
  Đầu mỗi retrain cycle. Ghi report vào meta.json để track drift theo thời gian.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


_MIN_SAMPLES_FIT = 30
_BIAS_REVIEW_THRESHOLD_DB = 5.0
_SIGMA_REVIEW_THRESHOLD_DB = 12.0


@dataclass(frozen=True, slots=True)
class Stage1RecalReport:
    """Residual drift signal cho Stage 1 ITU-R P.1812.

    Trường:
        bias_db: mean(residual). > 0 = measured > stage1 (model dự đoán PL quá lớn).
        sigma_db: std(residual). Gauge shadow fading + lỗi DEM/clutter (idealy ~σ env_profile).
        n_samples: số sample tham gia fit.
        bias_review_threshold_db: ngưỡng |bias| để recommend review.
        sigma_review_threshold_db: ngưỡng σ để recommend review.
        recommend_review: True nếu |bias_db| > threshold hoặc sigma_db > threshold.
    """

    bias_db: float
    sigma_db: float
    n_samples: int
    bias_review_threshold_db: float
    sigma_review_threshold_db: float
    recommend_review: bool


def recalibrate(
    train_df: pd.DataFrame,
    residual_col: str = "residual_db",
) -> Stage1RecalReport:
    """Compute bias + σ residual trên train_df.

    Args:
        train_df: training DataFrame có cột `residual_col` = measured - stage1.
        residual_col: tên cột residual.

    Returns:
        Stage1RecalReport.

    Raises:
        ValueError: < _MIN_SAMPLES_FIT sample finite.
    """
    if len(train_df) < _MIN_SAMPLES_FIT:
        msg = f"Stage 1 recal needs ≥ {_MIN_SAMPLES_FIT} samples; got {len(train_df)}"
        raise ValueError(msg)

    residual = train_df[residual_col].to_numpy(dtype=np.float64)
    mask = np.isfinite(residual)
    residual = residual[mask]
    if residual.size < _MIN_SAMPLES_FIT:
        msg = f"After non-finite drop: {residual.size} < {_MIN_SAMPLES_FIT}"
        raise ValueError(msg)

    bias = float(np.mean(residual))
    sigma = float(np.std(residual, ddof=1))
    recommend = (abs(bias) > _BIAS_REVIEW_THRESHOLD_DB) or (sigma > _SIGMA_REVIEW_THRESHOLD_DB)

    report = Stage1RecalReport(
        bias_db=bias,
        sigma_db=sigma,
        n_samples=int(residual.size),
        bias_review_threshold_db=_BIAS_REVIEW_THRESHOLD_DB,
        sigma_review_threshold_db=_SIGMA_REVIEW_THRESHOLD_DB,
        recommend_review=bool(recommend),
    )
    log.info(
        "Stage1 recal (ITU): bias=%+.2f dB, σ=%.2f dB, n=%d, recommend_review=%s",
        report.bias_db,
        report.sigma_db,
        report.n_samples,
        report.recommend_review,
    )
    return report
