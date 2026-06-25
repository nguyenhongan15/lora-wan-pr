"""Stage 1 + optional Stage 2 orchestrator.

predict(target) = best_gateway(Stage1) → Stage2.predict_residual → RSSI += delta.
Stage1 (ITU-R P.1812) chọn gateway theo physics ranking + tính RSSI baseline.
Stage2 (Extra Trees end-to-end) trả `residual_db = rssi_et - rssi_stage1`;
cộng vào → RSSI cuối = RSSI dự đoán end-to-end của ET. Stage1 effectively chỉ
còn vai trò gateway selection + baseline cho metric phụ.

Design choice: refine sau khi chọn (1 Stage2 call), KHÔNG refine từng candidate.
Lý do:
  - Latency: 1 HTTP call thay vì N (5 candidate x 50ms ≈ 250ms vs 50ms).
  - Stage1 ranking dựa trên link-budget margin — physics đáng tin cho rank;
    Stage2 absolute prediction chỉ tinh chỉnh giá trị dB cho gateway thắng.

Fallback: Stage2 fail (timeout/no model/network) → return Stage1 result thuần.
Define-errors-out: tất cả failure paths đều trả Stage1, log + telemetry.

12F VI stateless: orchestrator nắm reference tới sync CoverageQuery + async
Stage2Client. Mỗi request độc lập.
"""

from __future__ import annotations

import dataclasses
import logging

from ..domain.coverage import Confidence, ConfidenceMethod, Prediction, Target
from ..domain.errors import PredictionUnavailable
from ..domain.result import Err, Ok, Result
from .path_loss import (
    SF_SNR_LIMITS_DB,
    classify,
    detect_bottleneck_causes,
    estimate_ber,
    estimate_pdr,
    recommend_sf,
    status_worse_of,
)
from .repositories import CoverageQuery, GatewayDirectory
from .stage2 import Stage2Predictor

log = logging.getLogger(__name__)


class PredictionOrchestrator:
    """Async Stage 1 + Stage 2 predict.

    What:
      predict(target) → Result[Prediction, PredictionUnavailable].
    Hidden:
      Stage 1 sync call, gateway lookup, optional Stage 2 HTTP, residual apply,
      model_version annotation.
    Failure mode:
      Mọi Stage 2 failure path → trả Stage 1 Prediction (degraded mode).
      Stage 1 fail → trả error nguyên trạng.
    """

    def __init__(
        self,
        query: CoverageQuery,
        directory: GatewayDirectory,
        stage2: Stage2Predictor | None,
    ) -> None:
        self._query = query
        self._directory = directory
        self._stage2 = stage2

    async def predict(self, target: Target) -> Result[Prediction, PredictionUnavailable]:
        result = self._query.predict(target)
        if isinstance(result, Err):
            return result
        if self._stage2 is None:
            return result

        pred: Prediction = result.value
        if pred.serving_gateway_id is None:
            # Stage1 không xác định được gateway → Stage2 không có context.
            return result

        gateway = self._directory.get_by_id(pred.serving_gateway_id)
        if gateway is None:
            log.warning(
                "Stage1 chose gateway_id=%s but directory.get_by_id returned None — fallback Stage1",
                pred.serving_gateway_id,
            )
            return result

        stage2_out = await self._stage2.predict_residual(
            target, gateway, stage1_rssi_dbm=pred.uplink_rssi_dbm
        )
        if stage2_out is None:
            # Expected during bootstrap (no active model) hoặc transient failure.
            return result

        delta = stage2_out.residual_db
        if isinstance(pred.confidence, Confidence):
            # Dải ±σ trên UI = √(epistemic + aleatoric). Trước đây epistemic=0 nên
            # dải chỉ phản ánh shadow-fading, "tự tin thái quá" so với sai số ML
            # thực (~7 dB holdout). Đặt epistemic = max(0, MSE_holdout −
            # aleatoric) → tổng phương sai ≈ MSE holdout, KHÔNG double-count phần
            # shadow-fading đã nằm trong aleatoric (holdout RMSE đo trên RSSI thực
            # nên đã bao hàm fading). holdout_mse_db2 None → giữ epistemic cũ.
            epistemic = pred.confidence.epistemic_variance_db2
            if stage2_out.holdout_mse_db2 is not None:
                epistemic = max(
                    epistemic,
                    stage2_out.holdout_mse_db2 - pred.confidence.aleatoric_variance_db2,
                    0.0,
                )
            refined_confidence = dataclasses.replace(
                pred.confidence,
                method=ConfidenceMethod.RESIDUAL,
                epistemic_variance_db2=epistemic,
            )
        else:
            refined_confidence = pred.confidence

        # delta = (ET end-to-end RSSI) − (Stage1 RSSI) là dB shift đồng đều —
        # noise floor và sensitivity bất biến → SNR và margin shift cùng delta.
        # Tính lại để response self-consistent: SF khuyến nghị + status phản
        # ánh đúng giá trị ML end-to-end.
        ul_rssi = round(pred.uplink_rssi_dbm + delta, 2)
        dl_rssi = round(pred.downlink_rssi_dbm + delta, 2)
        ul_snr = round(pred.uplink_snr_db + delta, 2)
        dl_snr = round(pred.downlink_snr_db + delta, 2)
        ul_margin = round(pred.uplink_margin_db + delta, 2)
        dl_margin = round(pred.downlink_margin_db + delta, 2)
        sf = target.spreading_factor
        ul_status = classify(ul_rssi, ul_snr, sf)
        dl_status = classify(dl_rssi, dl_snr, sf)
        coverage_status = status_worse_of(ul_status, dl_status)
        worst_snr = ul_snr if ul_margin <= dl_margin else dl_snr

        # Stage 2 ET shift SNR đồng đều → PDR/BER/FER cập nhật theo margin mới;
        # ToA/jitter/bandwidth/shadow σ/noise floor/env không đổi.
        sf_limit = SF_SNR_LIMITS_DB[sf]
        worst_snr_margin_new = min(ul_snr - sf_limit, dl_snr - sf_limit)
        pdr_new = estimate_pdr(worst_snr_margin_new)
        ber_new = estimate_ber(worst_snr_margin_new)

        refined = dataclasses.replace(
            pred,
            rssi_dbm=dl_rssi,
            snr_db=dl_snr,
            coverage_status=coverage_status,
            recommended_sf=recommend_sf(worst_snr),
            uplink_rssi_dbm=ul_rssi,
            uplink_snr_db=ul_snr,
            uplink_margin_db=ul_margin,
            uplink_status=ul_status,
            downlink_rssi_dbm=dl_rssi,
            downlink_snr_db=dl_snr,
            downlink_margin_db=dl_margin,
            downlink_status=dl_status,
            model_version=f"{pred.model_version}+{stage2_out.model_version}",
            confidence=refined_confidence,
            pdr=round(pdr_new, 4),
            ber=ber_new,
            fer=round(1.0 - pdr_new, 4),
        )
        # Re-detect causes vì Stage 2 đã shift SNR/recommended_sf → snr_low &
        # sf_mismatch có thể flip; path_loss/interference/tx_power_cap không
        # đổi (PL & NF bất biến sau khi cộng delta).
        refined = dataclasses.replace(
            refined, bottleneck_causes=detect_bottleneck_causes(refined, target)
        )
        return Ok(refined)
