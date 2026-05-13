"""Stage 1 recalibration — fit path-loss exponent n + σ trên data hiện tại, emit report.

What:
  recalibrate(train_df) → Stage1RecalReport (n_obs, sigma_obs, intercept,
  n_current, delta_n).
Hidden:
  Linear regression rssi_measured ~ a + b * log10(distance_km), với b = -10n.
  Robust fit: dùng numpy lstsq (least-squares). σ = RMSE residual.
Failure mode:
  < 30 sample → ValueError (không đủ cho linear fit reliable).
  All-same distance → singular matrix → ValueError.

Lý do report-only, KHÔNG auto-update Stage 1 config:
  Stage 1 config được manage manually + version-control hóa. Auto-update sẽ
  làm "physics baseline" trôi theo data — ngược triết lý "physics làm rào
  chắn bất biến". Recal output là tín hiệu cho human: nếu Δn > 0.5 hoặc
  σ > 25 dB, review fit_path_loss_exponent.sql + cân nhắc đổi.

Khi nào gọi:
  Đầu mỗi retrain cycle (monthly cron). Ghi report vào meta.json để track
  drift theo thời gian.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


_MIN_SAMPLES_FIT = 30

# Cutoff distance khi fit path-loss. Sample d < cutoff bị multipath / near-field
# distortion (Stage 1 validity domain: outdoor 2-30 km). Smoke run đầu fit trên
# full data ra n_obs=0.06 (slope ≈ 0) vì DN data tập trung dày đặc < 1 km
# quanh gateway nên slope dB-vs-log10(d) gần flat. Filter ≥ 0.5 km loại near-
# field samples → fit phản ánh path-loss thật.
_DEFAULT_MIN_DISTANCE_KM = 0.5


@dataclass(frozen=True, slots=True)
class Stage1RecalReport:
    """Kết quả fit + so sánh với Stage 1 hiện tại.

    Trường:
        n_obs: path-loss exponent fit từ data (≈ 2-4 cho outdoor).
        sigma_obs: σ của residual sau fit (dB) — gauge shadow fading magnitude.
        intercept_db: a trong RSSI = a - 10·n·log10(d).
        n_current: n đang dùng trong Stage 1 EnvironmentalProfile.
        delta_n: n_obs - n_current. > 0 = data "loss nhanh hơn" model.
        n_samples: số sample dùng fit (đã lọc d ≥ min_distance_km).
        min_distance_km: ngưỡng cutoff dùng cho fit.
        recommend_update: True nếu |delta_n| > 0.5 hoặc sigma_obs > 25.
    """

    n_obs: float
    sigma_obs: float
    intercept_db: float
    n_current: float
    delta_n: float
    n_samples: int
    min_distance_km: float
    recommend_update: bool


def recalibrate(
    train_df: pd.DataFrame,
    n_current: float,
    distance_col: str = "log10_distance_to_serving_gw_km",
    rssi_col: str = "rssi_dbm_measured",
    min_distance_km: float = _DEFAULT_MIN_DISTANCE_KM,
) -> Stage1RecalReport:
    """Fit log-distance path loss model trên train_df (lọc d ≥ min_distance_km).

    RSSI(d) = a + b · log10(d_km),  với b = -10·n_obs.

    Args:
        train_df: training DataFrame (đã filter outdoor + serving GW non-null).
        n_current: path-loss exponent hiện tại của Stage 1 EnvironmentalProfile.
        distance_col: tên cột log10(distance km). Default khớp data.py.
        rssi_col: tên cột RSSI measured (dBm).
        min_distance_km: cutoff loại near-field samples. Lý do: Stage 1 valid
            domain là outdoor 2-30 km; gần gateway có multipath + LOS-dominated
            không tuân log-distance → slope bị flatten.

    Returns:
        Stage1RecalReport.

    Raises:
        ValueError: < _MIN_SAMPLES_FIT sample (sau filter) hoặc distance column
            hằng số (cùng cell).
    """
    if len(train_df) < _MIN_SAMPLES_FIT:
        msg = f"Stage 1 recal needs ≥ {_MIN_SAMPLES_FIT} samples; got {len(train_df)}"
        raise ValueError(msg)

    log10_cutoff = math.log10(min_distance_km)
    x_full = train_df[distance_col].to_numpy(dtype=np.float64)
    y_full = train_df[rssi_col].to_numpy(dtype=np.float64)
    mask = np.isfinite(x_full) & np.isfinite(y_full) & (x_full >= log10_cutoff)
    n_filtered_out = int((~mask).sum())
    x, y = x_full[mask], y_full[mask]
    log.info(
        "Stage1 recal filter: kept %d/%d samples (d ≥ %.2f km dropped %d)",
        x.size,
        len(train_df),
        min_distance_km,
        n_filtered_out,
    )
    if x.size < _MIN_SAMPLES_FIT:
        msg = (
            f"After filter d ≥ {min_distance_km} km + non-finite drop: "
            f"{x.size} < {_MIN_SAMPLES_FIT}"
        )
        raise ValueError(msg)
    if np.std(x) < 1e-9:
        msg = f"Column {distance_col} is constant → cannot fit slope"
        raise ValueError(msg)

    # lstsq Ax=b với A = [log10(d), 1] → slope b, intercept a.
    # Giữ tên A (uppercase) theo convention toán lstsq — design matrix.
    A = np.column_stack([x, np.ones_like(x)])  # noqa: N806
    (slope, intercept), *_ = np.linalg.lstsq(A, y, rcond=None)
    n_obs = float(-slope / 10.0)
    y_pred = A @ np.array([slope, intercept])
    sigma_obs = float(np.sqrt(np.mean((y - y_pred) ** 2)))
    delta_n = n_obs - n_current
    recommend = (abs(delta_n) > 0.5) or (sigma_obs > 25.0)

    report = Stage1RecalReport(
        n_obs=n_obs,
        sigma_obs=sigma_obs,
        intercept_db=float(intercept),
        n_current=float(n_current),
        delta_n=delta_n,
        n_samples=int(x.size),
        min_distance_km=float(min_distance_km),
        recommend_update=bool(recommend),
    )
    log.info(
        "Stage1 recal: n_obs=%.3f (current=%.3f, Δ=%+.3f), σ=%.2f dB, n=%d, recommend=%s",
        report.n_obs,
        report.n_current,
        report.delta_n,
        report.sigma_obs,
        report.n_samples,
        report.recommend_update,
    )
    return report
