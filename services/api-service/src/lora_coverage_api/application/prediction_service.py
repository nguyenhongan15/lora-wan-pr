"""Stage 1 + optional Stage 2 orchestrator.

Plan v1 §5: predict(target) = best_gateway(Stage1) → Stage2.predict_residual →
RSSI += residual. Stage1 picks gateway (physics ranking), Stage2 refines RSSI.

Design choice: refine sau khi chọn (1 Stage2 call), KHÔNG refine từng candidate.
Lý do:
  - Latency: 1 HTTP call thay vì N (5 candidate x 50ms ≈ 250ms vs 50ms).
  - Stage1 ranking dựa trên link-budget margin — physics đáng tin. Stage2
    correction là dB delta < ±15 dB → unlikely đảo lộn ranking.

Fallback: Stage2 fail (timeout/no model/network) → return Stage1 result thuần.
Define-errors-out: tất cả failure paths đều trả Stage1, log + telemetry.

12F VI stateless: orchestrator nắm reference tới sync CoverageQuery + async
Stage2Client. Mỗi request độc lập.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Literal

from ..domain.coverage import Confidence, ConfidenceMethod, CoverageStatus, Prediction, Target
from ..domain.errors import PredictionUnavailable
from ..domain.result import Err, Ok, Result
from .path_loss import classify, recommend_sf, status_worse_of
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
        refined_confidence = (
            dataclasses.replace(pred.confidence, method=ConfidenceMethod.RESIDUAL)
            if isinstance(pred.confidence, Confidence)
            else pred.confidence
        )

        # Residual cộng vào RSSI là dB shift đồng đều — noise floor và sensitivity
        # bất biến → SNR và margin shift cùng delta. Tính lại để response self-
        # consistent: SF khuyến nghị + status phản ánh được "máy học nói khoẻ
        # hơn vật lý dự đoán bao nhiêu".
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
        # Bottleneck: margin diff không đổi sau shift đồng đều, nhưng status có
        # thể chuyển sang STRONG cho cả 2 chiều → "both_ok" eligible. Logic
        # khớp resolve_bottleneck(); inline để tránh construct LinkBudget tạm.
        bottleneck: Literal["uplink", "downlink", "both_ok"]
        if (
            abs(ul_margin - dl_margin) <= 1.0
            and ul_status == CoverageStatus.STRONG
            and dl_status == CoverageStatus.STRONG
        ):
            bottleneck = "both_ok"
        else:
            bottleneck = "uplink" if ul_margin <= dl_margin else "downlink"

        refined = dataclasses.replace(
            pred,
            rssi_dbm=dl_rssi,
            snr_db=dl_snr,
            coverage_status=coverage_status,
            recommended_sf=recommend_sf(worst_snr),
            bottleneck=bottleneck,
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
        )
        return Ok(refined)
