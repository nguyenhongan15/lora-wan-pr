"""Phase 0 — So sánh CÁCH KẾT HỢP vật lý (P.1812) + ML trên holdout không gian.

Quyết định (bằng số liệu) cách fuse Stage1 + Stage2 trước khi đổi production:
  M_abs   — ExtraTrees target tuyệt đối (hiện tại). final = rssi_et.
  M_res   — target = rssi - stage1_rssi_dbm. final = stage1 + residual (fusion thật,
            suy biến về vật lý khi residual→0).
  M_feat  — target tuyệt đối + thêm stage1_rssi_dbm vào feature (physics-as-feature).
  physics — P.1812 thuần (= cột stage1_rssi_dbm). Sàn dưới / cận khi xa dữ liệu.

Eval trên **holdout không gian trung thực** (`data_split='test'`) + **đường cong OOD**
(RMSE theo khoảng-cách-tới-điểm-train gần nhất) → cho thấy mô hình nào suy biến mượt
về vật lý ở vùng chưa khảo sát.

Tái dùng CHÍNH pipeline train (`train_extra_trees.build_pipeline`) để parity tuyệt đối.
Yêu cầu CSV đã có cột `stage1_rssi_dbm` (build_training_csv.py --with-stage1-rssi).

Chạy trong celery-worker (đã có sklearn + CSV):
    docker compose exec celery-worker python \
        /app/scripts/experiments/eval_fusion_methods.py \
        --out /app/reports/fusion_methods.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Console Windows mặc định cp1252 → in tiếng Việt vỡ; ép UTF-8 (no-op trên Linux).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass

# Import pipeline train để dùng ĐÚNG cấu hình (NUMERIC_FEATURES, ET_PARAMS, ...).
_SCRIPTS = Path("/app/services/ml-service/scripts")
_SCRIPTS_LOCAL = Path(__file__).resolve().parents[2] / "services/ml-service/scripts"
for _p in (_SCRIPTS, _SCRIPTS_LOCAL):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import train_extra_trees as tet  # noqa: E402

EARTH_KM = 6371.0088
OOD_BINS = [(0.0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, 1e9)]


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = y_pred - y_true
    if len(err) == 0:
        return {"n": 0}
    ss_res = float(np.sum(err**2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2)) or float("nan")
    return {
        "n": len(err),
        "rmse_db": float(np.sqrt(np.mean(err**2))),
        "mae_db": float(np.mean(np.abs(err))),
        "bias_db": float(np.mean(err)),  # predicted - measured
        "r2": float(1 - ss_res / ss_tot),
    }


def _nearest_train_dist_km(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Khoảng cách (km) từ mỗi điểm test tới điểm TRAIN gần nhất — trục OOD."""
    try:
        from sklearn.neighbors import BallTree

        tr = np.radians(train[["lat", "lon"]].to_numpy())
        te = np.radians(test[["lat", "lon"]].to_numpy())
        bt = BallTree(tr, metric="haversine")
        d, _ = bt.query(te, k=1)
        return d[:, 0] * EARTH_KM
    except Exception:  # fallback O(n*m) nếu sklearn thiếu BallTree
        tr = train[["lat", "lon"]].to_numpy()
        out = np.empty(len(test))
        for i, (la, lo) in enumerate(test[["lat", "lon"]].to_numpy()):
            dlat = np.radians(tr[:, 0] - la)
            dlon = np.radians(tr[:, 1] - lo)
            a = (
                np.sin(dlat / 2) ** 2
                + np.cos(np.radians(la)) * np.cos(np.radians(tr[:, 0])) * np.sin(dlon / 2) ** 2
            )
            out[i] = (2 * EARTH_KM * np.arcsin(np.sqrt(a))).min()
        return out


def _fit_predict_abs(
    train: pd.DataFrame, test: pd.DataFrame, numeric_features: list[str], residual: bool
) -> np.ndarray:
    """Fit 1 biến thể, trả dự đoán ở KHÔNG GIAN RSSI TUYỆT ĐỐI (so sánh công bằng)."""
    feature_cols = numeric_features + tet.CATEGORICAL_FEATURES
    pipe = tet.build_pipeline(numeric_features)
    y_tr = (
        (train["rssi"] - train[tet.STAGE1_COL]).to_numpy() if residual else train["rssi"].to_numpy()
    )
    pipe.fit(train[feature_cols], y_tr)
    out = pipe.predict(test[feature_cols])
    return out + test[tet.STAGE1_COL].to_numpy() if residual else out


def _ood_table(y_true: np.ndarray, y_pred: np.ndarray, dist_km: np.ndarray) -> list[dict]:
    rows = []
    for lo, hi in OOD_BINS:
        m = (dist_km >= lo) & (dist_km < hi)
        if not m.any():
            continue
        r = _metrics(y_true[m], y_pred[m])
        r["bin_km"] = f"{lo}-{hi if hi < 1e8 else 'inf'}"
        rows.append(r)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=str(tet.DATA_PATH))
    ap.add_argument("--out", type=Path, default=Path("/app/reports/fusion_methods.json"))
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    if tet.STAGE1_COL not in df.columns:
        raise SystemExit(
            f"CSV thiếu '{tet.STAGE1_COL}'. Chạy: build_training_csv.py --with-stage1-rssi trước."
        )
    # Loại row stage1 NaN để mọi biến thể so trên CÙNG tập (công bằng).
    df = df[df[tet.STAGE1_COL].notna()].reset_index(drop=True)
    train = df[df["data_split"] == "train"].reset_index(drop=True)
    test = df[df["data_split"] == "test"].reset_index(drop=True)
    if len(train) == 0 or len(test) == 0:
        raise SystemExit(f"train={len(train)} test={len(test)} — cần cả hai > 0")

    y_true = test["rssi"].to_numpy()
    dist_km = _nearest_train_dist_km(train, test)
    print(
        f"train={len(train)} test={len(test)}  dist_to_train_km: "
        f"median={np.median(dist_km):.2f} p90={np.percentile(dist_km, 90):.2f}"
    )

    variants: dict[str, np.ndarray] = {
        "physics_only": test[tet.STAGE1_COL].to_numpy(),
        "M_abs": _fit_predict_abs(train, test, tet.NUMERIC_FEATURES, residual=False),
        "M_res": _fit_predict_abs(train, test, tet.NUMERIC_FEATURES, residual=True),
        "M_feat": _fit_predict_abs(
            train, test, [*tet.NUMERIC_FEATURES, tet.STAGE1_COL], residual=False
        ),
    }

    summary: dict = {"n_train": len(train), "n_test": len(test), "methods": {}}
    print(f"\n{'method':<14} {'RMSE':>7} {'MAE':>7} {'bias':>7} {'R2':>7}")
    print("-" * 46)
    for name, pred in variants.items():
        overall = _metrics(y_true, pred)
        summary["methods"][name] = {
            "overall": overall,
            "ood_bins": _ood_table(y_true, pred, dist_km),
        }
        print(
            f"{name:<14} {overall['rmse_db']:>7.2f} {overall['mae_db']:>7.2f} "
            f"{overall['bias_db']:>+7.2f} {overall['r2']:>7.3f}"
        )

    print("\nRMSE theo khoảng cách tới train (đường cong OOD):")
    print(f"{'bin_km':<12}" + "".join(f"{n:>14}" for n in variants))
    for bi, (lo, hi) in enumerate(OOD_BINS):
        label = f"{lo}-{hi if hi < 1e8 else 'inf'}"
        cells = []
        for name in variants:
            bins = summary["methods"][name]["ood_bins"]
            match = bins[bi] if bi < len(bins) and bins[bi]["bin_km"] == label else None
            cells.append(f"{match['rmse_db']:.2f}(n{match['n']})" if match else "-")
        print(f"{label:<12}" + "".join(f"{c:>14}" for c in cells))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))
    print(f"\nSaved → {args.out}")
    print(
        "\nĐọc: chọn method RMSE holdout thấp nhất MÀ ở bin OOD xa (5-inf) tiến gần "
        "physics_only (suy biến mượt). M_abs xa dữ liệu thường tệ hơn physics → "
        "không an toàn cho bản đồ; M_res kỳ vọng ≈ physics ở bin xa."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
