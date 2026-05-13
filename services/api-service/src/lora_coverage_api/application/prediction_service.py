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

from ..domain.coverage import Prediction, Target
from ..domain.errors import PredictionUnavailable
from ..domain.result import Err, Ok, Result
from ..infrastructure.stage2_client import Stage2Client
from .repositories import CoverageQuery, GatewayDirectory

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
        stage2: Stage2Client | None,
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

        stage2_out = await self._stage2.predict_residual(target, gateway)
        if stage2_out is None:
            # Expected during bootstrap (no active model) hoặc transient failure.
            return result

        delta = stage2_out.residual_db
        refined = dataclasses.replace(
            pred,
            rssi_dbm=round(pred.rssi_dbm + delta, 2),
            uplink_rssi_dbm=round(pred.uplink_rssi_dbm + delta, 2),
            downlink_rssi_dbm=round(pred.downlink_rssi_dbm + delta, 2),
            model_version=f"{pred.model_version}+{stage2_out.model_version}",
        )
        # NOTE: coverage_status/margins giữ từ Stage 1 — re-classify cần access
        # path_loss._classify (module-private). Phase 7 refactor: expose
        # classify() public + áp residual cho margin trước classify.
        return Ok(refined)
