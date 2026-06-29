"""CoverageQuery use case (application layer).

Chọn serving gateway tốt nhất từ danh sách candidates rồi predict.
Phụ thuộc 2 thứ qua DI: GatewayDirectory + PathLossModel.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from ..domain.coverage import CoverageStatus, Gateway, Prediction, Target
from ..domain.errors import PredictionErrorCode, PredictionUnavailable
from ..domain.result import Err, Ok, Result
from ..domain.survey import haversine_km
from .path_loss import PathLossModel, detect_bottleneck_causes
from .repositories import GatewayDirectory

# Gateway trong bán kính này coi như CÙNG MỘT site vật lý. Nhiều site triển khai
# 2-4 radio cùng tọa độ nhưng khác `code`/`id` (gateway_table.csv: 4 gw trùng
# tọa độ 16.0740984,108.15253). 80m đủ rộng để gộp twin nhưng không nuốt 2 site
# thật khác nhau (site thưa hơn nhiều ở VN).
COLOCATION_RADIUS_M = 80.0


def _dedupe_colocated(candidates: Sequence[Gateway]) -> list[Gateway]:
    """Gộp gateway đồng vị trí (≤ COLOCATION_RADIUS_M) thành 1 đại diện/site.

    Lý do: Stage 2 dùng feature `gateway` one-hot nên chọn "anh em sinh đôi"
    khác mã → dự đoán RSSI dao động dù cùng vị trí, lệch với RSSI đo của gateway
    thực thu gói. Gộp thành 1 site loại nhiễu chọn-sai-twin + cho
    `covering_gateway_count` đếm redundancy theo site (không phải theo số radio).

    `candidates` đã sort theo khoảng cách tăng dần (hợp đồng GatewayDirectory)
    nên anchor cluster = thành viên gần nhất; site gần nhất giữ thứ tự đứng trước.
    Đại diện mỗi cluster = anten cao nhất (thu tốt nhất), tie-break theo str(id)
    để deterministic.
    """
    clusters: list[list[Gateway]] = []
    for gw in candidates:
        for cluster in clusters:
            anchor = cluster[0]
            d_m = (
                haversine_km(gw.latitude, gw.longitude, anchor.latitude, anchor.longitude) * 1000.0
            )
            if d_m <= COLOCATION_RADIUS_M:
                cluster.append(gw)
                break
        else:
            clusters.append([gw])
    return [max(cluster, key=lambda g: (g.antenna_height_m, str(g.id))) for cluster in clusters]


class CoverageQueryService:
    def __init__(self, directory: GatewayDirectory, model: PathLossModel) -> None:
        self._directory = directory
        self._model = model

    def predict(self, target: Target) -> Result[Prediction, PredictionUnavailable]:
        candidates = self._directory.find_serving_candidates(target)
        if not candidates:
            return Err(
                PredictionUnavailable(
                    code=PredictionErrorCode.NO_GATEWAY_NEARBY,
                    message="Không có gateway nào trong bán kính 30km.",
                )
            )

        # Gộp gateway đồng vị trí thành 1 site TRƯỚC khi predict — tránh chọn
        # nhầm "anh em sinh đôi" khác mã (one-hot Stage 2 khác → RSSI dao động).
        sites = _dedupe_colocated(candidates)

        # Predict trên mỗi site, chọn gateway có bottleneck margin lớn nhất
        # (= min(UL margin, DL margin)). Bottleneck-aware vì link 2 chiều phải
        # đảm bảo: 1 GW có DL strong nhưng UL chết do RX gain thấp sẽ KHÔNG
        # phục vụ được — chọn theo top-level rssi_dbm (DL only) sẽ bias sai.
        #
        # Đồng thời đếm số SITE có status != NO_COVERAGE = "phủ sóng được" —
        # diversity metric cho FE hiển thị (1 site = single point of failure,
        # ≥2 = redundancy). Đếm theo site (sau dedup) chứ không theo số radio.
        best: Prediction | None = None
        best_margin: float = float("-inf")
        covering = 0
        for gw in sites:
            p = self._model.predict(target, gw)
            if p.coverage_status != CoverageStatus.NO_COVERAGE:
                covering += 1
            margin = min(p.uplink_margin_db, p.downlink_margin_db)
            if margin > best_margin:
                best = p
                best_margin = margin

        assert best is not None  # sites không rỗng (candidates non-empty) → best có giá trị
        causes = detect_bottleneck_causes(best, target)
        return Ok(
            dataclasses.replace(best, covering_gateway_count=covering, bottleneck_causes=causes)
        )
