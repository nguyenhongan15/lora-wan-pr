"""
ml/model_store.py — Lưu và load trained ML models.

Mỗi model bundle gồm:
  - scaler     : StandardScaler đã fit
  - models     : dict {algorithm_name: fitted_model}
  - meta       : dict thông tin (feature_names, metrics, timestamp...)

Lưu dưới dạng: backend/ml_models/<model_id>.joblib
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

logger = logging.getLogger(__name__)

# Thư mục lưu model — tạo tự động nếu chưa có
MODEL_DIR = Path(__file__).parent.parent / "ml_models"
MODEL_DIR.mkdir(exist_ok=True)


class ModelBundle:
    """Container cho tất cả thứ liên quan đến một lần train."""

    def __init__(
        self,
        model_id: str,
        algorithm: str,
        model: Any,                      # fitted sklearn/xgb model
        scaler: Any,                     # fitted StandardScaler
        feature_names: list[str],
        metrics: dict[str, float],
        hyperparameters: dict | None = None,
        feature_importance: dict | None = None,
        quantile_models: dict | None = None,
    ):
        self.model_id         = model_id
        self.algorithm        = algorithm
        self.model            = model
        self.scaler           = scaler
        self.feature_names    = feature_names
        self.metrics          = metrics
        self.hyperparameters  = hyperparameters or {}
        self.feature_importance = feature_importance or {}
        self.quantile_models  = quantile_models or {}
        self.trained_at       = datetime.now(timezone.utc).isoformat()


def save(bundle: ModelBundle) -> Path:
    """
    Lưu model bundle ra file .joblib.
    Trả về đường dẫn file đã lưu.
    """
    path = MODEL_DIR / f"{bundle.model_id}.joblib"
    joblib.dump(bundle, str(path), compress=3)
    logger.info("[ModelStore] Saved %s → %s", bundle.algorithm, path.name)
    return path


def load(model_id: str) -> ModelBundle:
    """
    Load model bundle theo model_id.
    Raise FileNotFoundError nếu không tồn tại.
    """
    path = MODEL_DIR / f"{model_id}.joblib"
    if not path.exists():
        raise FileNotFoundError(f"Model {model_id} not found at {path}")
    bundle: ModelBundle = joblib.load(str(path))
    logger.info("[ModelStore] Loaded %s (%s)", bundle.algorithm, model_id)
    return bundle


def exists(model_id: str) -> bool:
    return (MODEL_DIR / f"{model_id}.joblib").exists()


def list_models() -> list[dict]:
    """Liệt kê tất cả model đã lưu (chỉ meta, không load model object)."""
    result = []
    for p in sorted(MODEL_DIR.glob("*.joblib"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            bundle: ModelBundle = joblib.load(str(p))
            result.append({
                "model_id"    : bundle.model_id,
                "algorithm"   : bundle.algorithm,
                "trained_at"  : bundle.trained_at,
                "metrics"     : bundle.metrics,
                "feature_count": len(bundle.feature_names),
            })
        except Exception as e:
            logger.warning("Cannot read %s: %s", p.name, e)
    return result


def delete(model_id: str) -> bool:
    path = MODEL_DIR / f"{model_id}.joblib"
    if path.exists():
        path.unlink()
        logger.info("[ModelStore] Deleted %s", model_id)
        return True
    return False