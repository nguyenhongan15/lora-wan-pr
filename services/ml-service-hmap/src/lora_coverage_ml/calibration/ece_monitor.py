"""ECE (Expected Calibration Error) monitor.

SKELETON. Theo data-architecture.md:
  - Tính ECE trên rolling window survey gần nhất.
  - Cảnh báo khi ECE > 0.08 (threshold spec).
  - Trigger Platt/isotonic recalibration nếu drift kéo dài.
"""

from __future__ import annotations

__all__: list[str] = []
