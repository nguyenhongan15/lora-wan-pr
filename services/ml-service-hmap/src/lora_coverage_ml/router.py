"""Stage selection + auto-fallback.

SKELETON. Theo system-architecture.md §3.5:

  - Mỗi region cấu hình stage hiện tại (1/2/3/4).
  - Nếu stage cao không khả dụng (model không load được, ONNX runtime lỗi)
    → tự động fallback xuống stage thấp hơn cho đến Stage 1.
  - Stage 1 LUÔN khả dụng vì pure math (không phụ thuộc model artifact).
"""

from __future__ import annotations

# class StageRouter:
#     def __init__(self, region_stage_map: dict[str, int]) -> None: ...
#     def select(self, region: str) -> PathLossModel: ...
#     def fallback_chain(self, region: str) -> list[PathLossModel]: ...

__all__: list[str] = []
