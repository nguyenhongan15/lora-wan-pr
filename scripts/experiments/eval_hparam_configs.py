"""Khảo sát 3 cấu hình siêu tham số trên tập validation (residual model).

Đo RMSE/MAE/R² ở không gian RSSI tuyệt đối (residual → cộng lại stage1).
Chạy: docker compose exec -T celery-worker python /app/scripts/experiments/eval_hparam_configs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor

_SCRIPTS = Path("/app/services/ml-service/scripts")
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import train_extra_trees as tet  # noqa: E402

df = pd.read_csv(tet.DATA_PATH)
df = df[df[tet.STAGE1_COL].notna()].reset_index(drop=True)
tr = df[df["data_split"] == "train"].reset_index(drop=True)
va = df[df["data_split"] == "val"].reset_index(drop=True)
feat = tet.NUMERIC_FEATURES + tet.CATEGORICAL_FEATURES
ytr = (tr["rssi"] - tr[tet.STAGE1_COL]).to_numpy()  # nhãn residual
yva_abs = va["rssi"].to_numpy()
s1_va = va[tet.STAGE1_COL].to_numpy()

configs = [
    ("0,5", 5, 0.5, 5),
    ("None", 4, None, 4),
    ("None", 2, None, 2),
]
print(f"train={len(tr)} val={len(va)}\n")
print(f"{'max_features':>12} {'min_leaf':>9} {'RMSE':>7} {'MAE':>7} {'R2':>7}")
print("-" * 46)
for mf_label, leaf, mf, _ in configs:
    pipe = tet.build_pipeline(tet.NUMERIC_FEATURES)
    et = ExtraTreesRegressor(
        n_estimators=1500,
        max_depth=20,
        min_samples_split=5,
        min_samples_leaf=leaf,
        max_features=mf,
        random_state=42,
        n_jobs=-1,
    )
    pipe.steps[-1] = ("model", et)
    pipe.fit(tr[feat], ytr)
    pred_res = pipe.predict(va[feat])
    pred_abs = pred_res + s1_va
    err = pred_abs - yva_abs
    rmse = float(np.sqrt(np.mean(err**2)))
    mae = float(np.mean(np.abs(err)))
    r2 = float(1 - np.sum(err**2) / np.sum((yva_abs - yva_abs.mean()) ** 2))
    print(f"{mf_label:>12} {leaf:>9} {rmse:>7.2f} {mae:>7.2f} {r2:>7.3f}")
print("\nDONE")
