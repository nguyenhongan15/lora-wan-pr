"""Load artifact + reproduce dataset + run predictions cho evaluation.

What:
    load_eval_bundle(version) → EvalBundle với:
      - booster: lgb.Booster đã load
      - meta: meta.json dict (feature_columns, hyperparams, metrics, dataset_hash)
      - train_val, test: DataFrame có features + target + rssi_measured + snr_measured
      - y_pred_residual_test: ndarray Stage 2 dự đoán trên test
      - rssi_pred_test: ndarray Stage 1+2 dự đoán RSSI tổng hợp

Hidden:
    Re-fetch survey rows qua training.data.collect() — đảm bảo cùng pipeline
    với training (Stage 1 predict + feature extract). Verify dataset_hash khớp
    với artifact meta để đảm bảo đang eval đúng dataset đã train.

Failure mode:
    - Artifact missing → FileNotFoundError với path rõ ràng.
    - dataset_hash mismatch → log warning (data drift hoặc DB đã thay đổi), tiếp tục.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from lora_ml_predict.config import Settings
from lora_ml_predict.training.data import collect
from lora_ml_predict.training.registry_writer import load_booster, load_meta
from lora_ml_predict.training.splitter import SpatialStratifiedSplitter

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EvalBundle:
    """Mọi input các plot module cần — gom thành 1 dataclass để CLI dễ pass.

    Tách `rssi_pred_test` ra ngoài thay vì compute trong plot module: nhất quán
    1 chỗ tính → dễ debug khi scatter và CM bất đồng.
    """

    model_version: str
    booster: lgb.Booster
    meta: dict
    feature_columns: tuple[str, ...]
    target_column: str
    train_val: pd.DataFrame
    test: pd.DataFrame
    y_pred_residual_test: np.ndarray
    rssi_pred_test: np.ndarray


def _verify_dataset_hash(
    train_val: pd.DataFrame,
    test: pd.DataFrame,
    target_column: str,
    expected: str,
) -> None:
    """Cảnh báo nếu dataset đã drift so với lúc train.

    Cùng formula với training.retrain._compute_dataset_hash để khớp.
    """
    parts = []
    for df in (train_val, test):
        h = pd.util.hash_pandas_object(
            df[["timestamp", "lat", "lon", target_column]],
            index=False,
        )
        parts.append(h.to_numpy().tobytes())
    actual = hashlib.sha256(b"".join(parts)).hexdigest()
    if actual != expected:
        log.warning(
            "dataset_hash mismatch: artifact=%s actual=%s — data có thể đã drift "
            "(survey rows thêm/sửa từ lúc train). Eval vẫn chạy nhưng số liệu "
            "có thể khác meta.json.",
            expected[:12],
            actual[:12],
        )
    else:
        log.info("dataset_hash khớp artifact: %s", actual[:12])


def _repo_root() -> Path:
    """Resolve repo root từ vị trí file này (4 levels up).

    services/ml-service-predict/evaluation/data_loader.py
    ↑↑↑↑ = lora-coverage/ repo root.

    Tại sao cần: pydantic-settings + .env + relative path đều resolve theo cwd;
    CLI có thể chạy từ service dir hoặc repo root → không đoán được. File anchor
    là deterministic.
    """
    return Path(__file__).resolve().parent.parent.parent.parent


def _load_settings() -> Settings:
    """Load Settings với .env anchored vào repo root + absolute artifact path."""
    root = _repo_root()
    env_path = root / ".env"
    settings = Settings(_env_file=str(env_path) if env_path.exists() else None)  # type: ignore[call-arg]
    # stage2_artifact_dir default là "services/ml-service-predict/artifacts/stage2"
    # — relative path resolve theo cwd. Lock về absolute repo-relative.
    if not Path(settings.stage2_artifact_dir).is_absolute():
        absolute = root / settings.stage2_artifact_dir
        # Pydantic Settings field là Path, gán lại OK trong instance.
        object.__setattr__(settings, "stage2_artifact_dir", absolute)
    return settings


def load_eval_bundle(model_version: str, settings: Settings | None = None) -> EvalBundle:
    """Entry point. Trả EvalBundle sẵn sàng cho mọi plot module."""
    settings = settings or _load_settings()
    artifact_root = Path(settings.stage2_artifact_dir) / model_version
    model_file = artifact_root / "model.lgb"
    if not model_file.exists():
        msg = f"Stage 2 artifact không tồn tại: {model_file}"
        raise FileNotFoundError(msg)

    log.info("Loading artifact: %s", artifact_root)
    booster = load_booster(str(model_file))
    meta = load_meta(str(model_file))
    feature_columns = tuple(meta["feature_columns"])
    target_column = meta["target_column"]
    categorical_features: list[str] = list(meta.get("categorical_features", []))
    category_maps: dict[str, list[str]] = meta.get("category_maps", {})

    log.info("Re-fetching dataset (Stage 1 + features) — ~90s với 9.5k rows")
    tf = collect(settings)

    # Plan v2: training dùng spatial stratified hold-out thay vì time-split.
    # data.collect() vẫn time-split (legacy) → concat lại rồi split tay y hệt
    # retrain.run_retrain() để bundle khớp tập đã train.
    combined = pd.concat([tf.train_val, tf.test], ignore_index=True)
    splitter = SpatialStratifiedSplitter(seed=settings.optuna_seed)
    split_labels = splitter.assign(combined)
    train_val_df = combined[split_labels == "train"].reset_index(drop=True)
    test_df = combined[split_labels == "test"].reset_index(drop=True)
    _verify_dataset_hash(train_val_df, test_df, target_column, meta["dataset_hash"])

    x_test = test_df[list(feature_columns)].copy()
    # LightGBM v4 yêu cầu predict-time categorical dtype + categories khớp train.
    # category_maps lưu list values lúc fit; unseen value → code -1 → default direction.
    for col in categorical_features:
        cats = category_maps.get(col)
        if cats is None:
            continue
        x_test[col] = pd.Categorical(x_test[col].astype(str), categories=cats)

    y_pred_residual = booster.predict(x_test, num_iteration=booster.best_iteration)
    # rssi_pred = rssi_measured - residual_true + residual_pred
    #           = rssi_stage1 + residual_pred
    rssi_stage1 = test_df["rssi_dbm_measured"].to_numpy() - test_df[target_column].to_numpy()
    rssi_pred = rssi_stage1 + np.asarray(y_pred_residual)

    return EvalBundle(
        model_version=model_version,
        booster=booster,
        meta=meta,
        feature_columns=feature_columns,
        target_column=target_column,
        train_val=train_val_df,
        test=test_df,
        y_pred_residual_test=np.asarray(y_pred_residual),
        rssi_pred_test=rssi_pred,
    )
