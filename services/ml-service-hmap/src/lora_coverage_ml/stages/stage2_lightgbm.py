"""Stage 2 — LightGBM residual model trên Stage 1 baseline.

SKELETON. Khi build:
  - Input: Stage 1 prediction + tabular features (distance, terrain bin,
    seasonal, gateway metadata).
  - Output: residual correction (dB) → final RSSI = stage1_rssi + residual.
  - Confidence: empirical CI từ residual std trên validation set.
  - Yêu cầu: ≥ 5000 survey điểm/region để train.
  - Export ONNX qua `onnxmltools` để dùng chung runtime.
"""

from __future__ import annotations

# class Stage2LightGBMModel:
#     model_version: str
#     def __init__(self, onnx_path: str): ...
#     def predict(self, target, gateway): ...

__all__: list[str] = []
