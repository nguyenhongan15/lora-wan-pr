"""Population Stability Index (PSI) — đo drift giữa reference vs current.

What:
  population_stability_index(reference, current, n_bins=10) → float PSI score.
Hidden:
  Bin theo quantile của reference (equal-frequency), tính tỷ lệ p_ref / p_cur
  mỗi bin, sum (p_cur - p_ref) * ln(p_cur / p_ref). Epsilon 1e-6 cho log/div.
Failure mode:
  Empty array → ValueError. NaN drop trước khi bin.

Diễn giải PSI (industry standard):
  < 0.10  : no significant shift.
  0.10-0.25: moderate drift, monitor.
  > 0.25  : significant drift → retrain.

Lý do equal-frequency thay equal-width:
  Equal-width bị dominate bởi outlier (1 bin chứa hầu hết mass, các bin khác
  trống). Quantile-based đảm bảo reference distribution rải đều → mỗi bin có
  đủ sample, PSI ổn định với skewed feature (vd log10_distance).
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)


_DEFAULT_N_BINS = 10
_EPS = 1e-6


def population_stability_index(
    reference: np.ndarray,
    current: np.ndarray,
    n_bins: int = _DEFAULT_N_BINS,
) -> float:
    """Tính PSI giữa 2 distribution.

    Args:
        reference: baseline distribution (training data), shape (n_ref,).
        current: new distribution (production / new batch), shape (n_cur,).
        n_bins: số quantile bins. 10 = decile (industry default).

    Returns:
        PSI score (float, ≥ 0). Càng cao = drift càng lớn.

    Raises:
        ValueError: array rỗng hoặc all-NaN sau khi drop.
    """
    ref = np.asarray(reference, dtype=np.float64)
    cur = np.asarray(current, dtype=np.float64)
    ref = ref[~np.isnan(ref)]
    cur = cur[~np.isnan(cur)]
    if ref.size == 0 or cur.size == 0:
        msg = "Cannot compute PSI: reference or current is empty / all-NaN"
        raise ValueError(msg)

    # Quantile-based bin edges từ reference. Dedupe edges để tránh 0-width bin
    # (xảy ra khi reference có nhiều giá trị trùng — vd SF12 dominant).
    quantiles = np.linspace(0.0, 1.0, n_bins + 1)
    edges = np.unique(np.quantile(ref, quantiles))
    if edges.size < 2:
        log.warning("Reference has only 1 unique value → PSI undefined, return 0")
        return 0.0
    # Mở rộng 2 đầu để cover cur ngoài range ref (ngoại lệ — vẫn count bin
    # ngoài cùng).
    edges[0] = -np.inf
    edges[-1] = np.inf

    ref_counts, _ = np.histogram(ref, bins=edges)
    cur_counts, _ = np.histogram(cur, bins=edges)

    p_ref = ref_counts / ref.size
    p_cur = cur_counts / cur.size
    # Epsilon tránh log(0) và div-by-zero khi 1 bin trống ở 1 phía.
    p_ref = np.where(p_ref == 0, _EPS, p_ref)
    p_cur = np.where(p_cur == 0, _EPS, p_cur)

    psi = float(np.sum((p_cur - p_ref) * np.log(p_cur / p_ref)))
    return psi
