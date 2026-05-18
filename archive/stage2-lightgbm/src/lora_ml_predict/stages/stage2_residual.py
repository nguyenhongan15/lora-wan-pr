"""Stage 2 (LightGBM residual) wrapper cho serving runtime.

What:
  Stage2ResidualModel.predict_residual(feature_vec) → float (dB delta).
Hidden:
  LightGBM booster load + DataFrame build với pandas Categorical dtype + feature
  column ordering.
Failure mode:
  Booster file missing/corrupt → load_from_disk raise FileNotFoundError/lgb error.
  predict_residual KHÔNG raise; nếu booster=None thì return 0.0 (= Stage1 only).

Stage 2 trả RESIDUAL (dB delta cộng vào Stage1 RSSI), không trả raw RSSI.
Lý do (plan §3): Stage1 đã encode vật lý cơ bản; Stage 2 chỉ học correction
→ smaller signal-to-noise, easier convergence với 9.5k DN samples.

Categorical dtype tại predict time PHẢI khớp training mapping (`category_maps`
trong meta.json) — unseen value (vd gateway_id mới) → code -1, LightGBM
treat missing và đi default direction. Hành vi xác định, no exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from ..features.extractor import FeatureVector
from ..training.registry_writer import load_booster, load_meta


@dataclass(frozen=True, slots=True)
class Stage2ResidualModel:
    """Thin wrapper: booster + feature columns + categorical maps + version.

    Immutable; service hot-reload bằng cách swap instance (atomic pointer).

    Trường:
        booster: lgb.Booster (Any-typed để tránh import lgb tại type-check time).
        feature_columns: tuple cột theo đúng order training (vd 12 cột v2).
        categorical_features: tuple cột categorical (LightGBM auto-detect khi
            DataFrame có category dtype).
        category_maps: {col: [values...]} — fixed category list từ training.
            Predict-time pd.Categorical(values, categories=this_list) đảm bảo
            cùng codes như training.
        feature_bounds: bounds cho OODDetector (lưu lại để client truy cập).
        guardrail_config: hằng số clip (lưu lại cho audit).
        model_version: string định danh.
    """

    booster: object  # lgb.Booster
    feature_columns: tuple[str, ...]
    categorical_features: tuple[str, ...]
    category_maps: dict[str, list[Any]]
    feature_bounds: dict[str, dict[str, Any]]
    guardrail_config: dict[str, float]
    model_version: str

    def predict_residual(self, fv: FeatureVector) -> float:
        """1 FeatureVector → float residual_db (cộng vào Stage1 RSSI ở caller).

        Build pandas DataFrame 1 hàng với categorical dtype khớp training map,
        gọi booster.predict. LightGBM nhận DataFrame trực tiếp + tự detect
        categorical từ dtype.
        """
        row_dict = {col: [getattr(fv, col)] for col in self.feature_columns}
        df = pd.DataFrame(row_dict)
        for col in self.categorical_features:
            cats = self.category_maps.get(col)
            if cats is not None:
                df[col] = pd.Categorical(df[col], categories=cats)
        pred = self.booster.predict(df)  # type: ignore[attr-defined]
        return float(pred[0])


def load_from_disk(artifact_uri: str, model_version: str) -> Stage2ResidualModel:
    """Load LightGBM booster + meta.json → Stage2ResidualModel.

    Backward-compatible: meta thiếu trường v2.0 (vd category_maps) → default
    rỗng, behavior fallback về v1 (numeric only).
    """
    booster = load_booster(artifact_uri)
    meta = load_meta(artifact_uri)
    feature_columns = tuple(meta["feature_columns"])
    categorical_features = tuple(meta.get("categorical_features", ()))
    category_maps = dict(meta.get("category_maps", {}))
    feature_bounds = dict(meta.get("feature_bounds", {}))
    guardrail_config = dict(meta.get("guardrail", {}))
    return Stage2ResidualModel(
        booster=booster,
        feature_columns=feature_columns,
        categorical_features=categorical_features,
        category_maps=category_maps,
        feature_bounds=feature_bounds,
        guardrail_config=guardrail_config,
        model_version=model_version,
    )
