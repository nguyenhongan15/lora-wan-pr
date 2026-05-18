"""Stage 2 training pipeline (Phase 4).

Composition root: orchestrator.run_training() ghép tất cả module:
    data → features → spatial CV → Optuna → LightGBM fit → registry write.

Mọi function pure / state đóng gói. Caller chỉ gọi `run_training(settings)`.
"""
