"""FastAPI app cho ml-service.

SKELETON. Khi implement:
  - POST /predict: nhận {lat, lng, sf, freq, gateway_id}, trả Prediction.
  - GET /healthz, /readyz.
  - Internal-only (network-isolated, không expose ra public).
  - Gọi router.py để chọn stage phù hợp cho region.
"""

from __future__ import annotations

# Khi build: from fastapi import FastAPI
# from .router import StageRouter
#
# app = FastAPI(title="LoRa Coverage ML Service", version="0.0.0")
# router = StageRouter()
#
# @app.post("/predict")
# async def predict(...): ...

__all__: list[str] = []
