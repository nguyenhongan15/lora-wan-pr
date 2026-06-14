"""Quick breakdown của ET hold-out RMSE theo SF + n-thresh per-bin.

Tách ra script riêng để không đụng eval_extra_trees_holdout.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import joblib
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "ml-service" / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import logging  # noqa: E402

from eval_extra_trees_holdout import (  # noqa: E402
    ALL_FEATURES,
    MODEL_PATH,
    compute_metrics,
    fetch_rows,
    rows_to_features,
)

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("breakdown")

db_url = os.environ["LORA_DB_URL"]
bbox = (15.8, 16.3, 107.9, 108.5)
rows = fetch_rows(db_url, "2026-01-01", "2026-02-28", bbox, 50.0)
df = rows_to_features(rows, log)

model = joblib.load(MODEL_PATH)
X = df[ALL_FEATURES]
y_true = df["__rssi"].to_numpy()
y_pred = model.predict(X)

print(f"\nTotal n={len(df)} unique_gw={df['gateway'].nunique()}")
print("\n=== Per SF ===")
for sf in sorted(df["spreading_factor"].unique()):
    mask = df["spreading_factor"].to_numpy() == sf
    if mask.sum() < 3:
        continue
    m = compute_metrics(y_true[mask], y_pred[mask])
    print(
        f"  SF{int(sf):>2}  n={m['n']:>4}  RMSE={m['rmse_db']:5.2f}  "
        f"MAE={m['mae_db']:5.2f}  bias={m['bias_db']:+5.2f}"
    )

print("\n=== Per gateway ===")
for gw in sorted(df["gateway"].unique()):
    mask = df["gateway"].to_numpy() == gw
    if mask.sum() < 3:
        continue
    m = compute_metrics(y_true[mask], y_pred[mask])
    print(
        f"  {gw:<20} n={m['n']:>4}  RMSE={m['rmse_db']:5.2f}  "
        f"MAE={m['mae_db']:5.2f}  bias={m['bias_db']:+5.2f}"
    )

print("\n=== Error percentiles ===")
err = np.abs(y_true - y_pred)
for p in [50, 75, 90, 95]:
    print(f"  P{p:<3} |err| = {np.percentile(err, p):.2f} dB")
print(f"  |err| ≤ 3 dB: {(err <= 3).mean() * 100:.1f}% rows")
print(f"  |err| ≤ 5 dB: {(err <= 5).mean() * 100:.1f}% rows")
print(f"  |err| ≤ 10 dB: {(err <= 10).mean() * 100:.1f}% rows")
