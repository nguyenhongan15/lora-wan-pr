"""Physics guardrail — clip ML residual + final RSSI về dải vật lý hợp lý.

What:
  clean(rssi_stage1, residual_pred) → (rssi_final, violated_flag).
Hidden:
  3 lớp check:
    1. Clip residual ∈ [-RESIDUAL_MAX_ABS_DB, +RESIDUAL_MAX_ABS_DB].
    2. Clip RSSI cuối ∈ [RSSI_MIN_DBM, RSSI_MAX_DBM].
    3. Set flag violated nếu raw |residual| vượt threshold (trước clip).
Failure mode:
  Input shape mismatch → ValueError. NaN propagate qua clip (numpy default).

Lý do tách module riêng:
  Guardrail dùng ở 2 nơi — training (eval metric ngay sau predict) và serving
  (output cuối). Cùng 1 logic → 1 module. Hằng số module-level (không class):
  guardrail không có state, không nhiều variant cần cấu hình runtime.

Hằng số biện luận:
  RESIDUAL_MAX_ABS_DB = 30  ≈ 3σ shadow fading (σ_obs ≈ 23 dB từ fit baseline).
                            Residual vượt 30 dB = ML chắc chắn ngoài phạm vi
                            học hợp lý → kẹp lại, log warning ở serving.
  RSSI_MIN_DBM = -150       Noise floor sub-GHz @ BW 125 kHz ≈ -125 dBm; -150
                            là margin an toàn (không cảm biến nào báo nhỏ hơn).
  RSSI_MAX_DBM = -30        Gateway RX saturation thực tế ~ -30 dBm; trên đó
                            front-end overload → giá trị không tin cậy.
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)


RESIDUAL_MAX_ABS_DB = 30.0
RSSI_MIN_DBM = -150.0
RSSI_MAX_DBM = -30.0


def clean(
    rssi_stage1: np.ndarray,
    residual_pred: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Áp guardrail: clip residual + clip RSSI cuối + flag vi phạm.

    Args:
        rssi_stage1: Stage 1 physics prediction (dBm), shape (n,).
        residual_pred: ML residual prediction (dB), shape (n,).

    Returns:
        rssi_final: clipped final RSSI (dBm), shape (n,).
        violated: bool flag mỗi sample = True nếu |raw residual| > threshold,
                  shape (n,). Caller dùng để log / serve Stage 1-only fallback.

    Raises:
        ValueError: shape mismatch giữa rssi_stage1 và residual_pred.
    """
    rssi_stage1 = np.asarray(rssi_stage1, dtype=np.float64)
    residual_pred = np.asarray(residual_pred, dtype=np.float64)
    if rssi_stage1.shape != residual_pred.shape:
        msg = (
            f"Shape mismatch: rssi_stage1={rssi_stage1.shape}, residual_pred={residual_pred.shape}"
        )
        raise ValueError(msg)

    violated = np.abs(residual_pred) > RESIDUAL_MAX_ABS_DB

    residual_clipped = np.clip(residual_pred, -RESIDUAL_MAX_ABS_DB, RESIDUAL_MAX_ABS_DB)
    rssi_raw = rssi_stage1 + residual_clipped
    rssi_final = np.clip(rssi_raw, RSSI_MIN_DBM, RSSI_MAX_DBM)

    n_viol = int(violated.sum())
    if n_viol > 0:
        log.info(
            "Guardrail flagged %d/%d sample(s): |residual| > %.1f dB",
            n_viol,
            len(violated),
            RESIDUAL_MAX_ABS_DB,
        )
    return rssi_final, violated
