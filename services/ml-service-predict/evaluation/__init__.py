"""Offline evaluation cho Stage 2 LightGBM residual model.

Sinh các biểu đồ đánh giá chất lượng:
  - Regression: scatter, residual, error histogram, Q-Q
  - Classification (derived coverage_status): confusion matrix, ROC, PR
  - Training diagnostics: boosting curve, CV per-fold
  - Interpretation: LightGBM feature importance, SHAP

Run:
    cd services/ml-service-predict
    uv run python -m evaluation.generate_report --version <model_version>

Output: evaluation/reports/<model_version>/*.png
"""
