"""Phase 0 — So sánh các CHIẾN LƯỢC chọn gateway trên holdout, end-to-end.

Mục đích: định lượng đòn bẩy "sửa chọn gateway" (báo cáo điều tra ML #2) TRƯỚC
khi đổi production. Khác các eval cũ:
  * `eval_api_predict_holdout.py` chỉ đo 1 chiến lược đang deploy (qua HTTP).
  * `archive/experiments/eval_actual_vs_best_gw_*.py` dùng model 8-feature lỗi thời.
Script này dùng **model active 21-feature** + **compute_link_features** (đúng
pipeline serving) + Stage 1 ITU thật, rồi thử NHIỀU chiến lược trong 1 lượt.

Cơ chế giá: final_RSSI = stage1 + (rssi_et - stage1) = **rssi_et** (Stage 1 triệt
tiêu trong residual). Nên final RSSI của 1 gateway = ET dự đoán tuyệt đối cho
gateway đó. Stage 1 chỉ dùng để XẾP HẠNG (margin) ở S0/S1.

Chiến lược so sánh (mỗi cái: chọn 1 gw → final = rssi_et của gw đó):
  S0  max min(UL,DL margin)  — logic production HIỆN TẠI (baseline).
  S1  max uplink margin       — survey ghi RSSI uplink → uplink là cái khớp.
  S2  max ET RSSI             — gateway ET dự đoán thu mạnh nhất.
  S3  nearest                 — gateway gần nhất.
  *_dedup  = chiến lược trên + gộp gw đồng vị trí (≤80m) thành 1 site
            (đại diện anten cao nhất) — DÙNG _dedupe_colocated của production.
  REF actual                  — dùng đúng gateway thực thu gói (cận trên).

Chạy trong celery-worker (có lora_coverage_api + crc_covlib + DEM + landuse):
    docker compose exec celery-worker python \
        /app/scripts/experiments/eval_gateway_selection_strategies.py \
        --out /app/reports/gateway_selection_strategies.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import psycopg

# --- Cho phép import compute_link_features (port serving) từ ml-service ---
_ML_SRC = Path("/app/services/ml-service/src")
if _ML_SRC.exists() and str(_ML_SRC) not in sys.path:
    sys.path.insert(0, str(_ML_SRC))
# fallback chạy ngoài container (repo-relative)
_ML_SRC_LOCAL = Path(__file__).resolve().parents[2] / "services/ml-service/src"
if _ML_SRC_LOCAL.exists() and str(_ML_SRC_LOCAL) not in sys.path:
    sys.path.insert(0, str(_ML_SRC_LOCAL))

from lora_coverage_api.application.coverage_service import (  # noqa: E402
    _dedupe_colocated,
)
from lora_coverage_api.application.itu.model import Stage1ItuModel  # noqa: E402
from lora_coverage_api.application.path_loss import resolve_environment_profile  # noqa: E402
from lora_coverage_api.domain.coverage import Gateway, GatewayId, Target  # noqa: E402
from lora_coverage_api.infrastructure.itu.crc_covlib_backend import (  # noqa: E402
    CrcCovlibBackend,
)
from lora_ml_predict.processing import compute_link_features  # noqa: E402

# Feature columns khớp services/ml-service/scripts/train_extra_trees.py + app.py.
NUMERIC_FEATURES = [
    "frequency",
    "spreading_factor",
    "log_distance",
    "log_distance_3d",
    "delta_lat",
    "delta_lon",
    "angle",
    "gw_elevation",
    "delta_elevation",
    "elevation_angle",
    "slope",
    "roughness",
    "terrain_mean",
    "terrain_std",
    "terrain_min",
    "terrain_max",
    "fresnel_obstruction_ratio",
    "min_fresnel_clearance",
    "mean_fresnel_clearance",
    "residential_ratio",
]
ALL_FEATURES = [*NUMERIC_FEATURES, "gateway"]

MAX_LINK_KM = 30.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(a, 1.0)))


def _gw_from_row(g: dict) -> Gateway:
    def _f(key):
        return float(g[key]) if g[key] is not None else None

    return Gateway(
        id=GatewayId(g["id"]),
        code=g["code"],
        name=g["name"],
        latitude=float(g["lat"]),
        longitude=float(g["lon"]),
        altitude_m=float(g["altitude_m"]),
        antenna_height_m=float(g["antenna_height_m"]),
        antenna_gain_dbi=float(g["antenna_gain_dbi"]),
        tx_power_dbm=float(g["tx_power_dbm"]),
        frequency_mhz=float(g["frequency_mhz"]),
        rx_antenna_gain_dbi=_f("rx_antenna_gain_dbi"),
        rx_sensitivity_dbm=_f("rx_sensitivity_dbm"),
        noise_floor_dbm=_f("noise_floor_dbm"),
    )


def _build_candidate_table(model, stage1, target: Target, cands: list[Gateway]) -> list[dict]:
    """Bảng per-candidate: gw, khoảng cách, UL/DL margin (Stage 1), ET RSSI.

    Tính 1 lần rồi dùng lại cho mọi chiến lược. Bỏ candidate nếu DEM lookup hỏng
    hoặc Stage 1 lỗi.
    """
    out: list[dict] = []
    for g in cands:
        et = _et_rssi(model, target, g)
        if et is None:
            continue
        try:
            p = stage1.predict(target, g)
        except Exception:
            continue
        out.append(
            {
                "gw": g,
                "d_km": haversine_km(target.latitude, target.longitude, g.latitude, g.longitude),
                "ul_margin": p.uplink_margin_db,
                "dl_margin": p.downlink_margin_db,
                "et_rssi": et,
            }
        )
    return out


def _et_rssi(model, target: Target, gw: Gateway) -> float | None:
    """ET RSSI tuyệt đối cho 1 link = final RSSI sau Stage2. None nếu DEM fail."""
    feats = compute_link_features(
        lat=target.latitude,
        lon=target.longitude,
        gw_lat=gw.latitude,
        gw_lon=gw.longitude,
        gw_ant_h_m=gw.antenna_height_m,
        freq_hz=gw.frequency_mhz * 1e6,
        sf=target.spreading_factor,
        gateway_code=gw.code,
    )
    if feats is None:
        return None
    X = pd.DataFrame([feats])[ALL_FEATURES]
    return float(model.predict(X)[0])


def _metrics(err: np.ndarray) -> dict:
    err = np.asarray(err, dtype=float)
    if len(err) == 0:
        return {"n": 0}
    return {
        "n": len(err),
        "rmse_db": float(np.sqrt(np.mean(err**2))),
        "mae_db": float(np.mean(np.abs(err))),
        "bias_db": float(np.mean(err)),  # predicted - measured
        "p90_abs_db": float(np.percentile(np.abs(err), 90)),
    }


# Mỗi chiến lược: (tên, hàm chọn index trong list cand, có dedup không).
# cand = list dict {gw, d_km, ul_margin, dl_margin, et_rssi}.
def _pick_s0(cand):  # max min(UL,DL) margin — production hiện tại
    return max(range(len(cand)), key=lambda i: min(cand[i]["ul_margin"], cand[i]["dl_margin"]))


def _pick_s1(cand):  # max uplink margin
    return max(range(len(cand)), key=lambda i: cand[i]["ul_margin"])


def _pick_s2(cand):  # max ET RSSI
    return max(range(len(cand)), key=lambda i: cand[i]["et_rssi"])


def _pick_s3(cand):  # nearest
    return min(range(len(cand)), key=lambda i: cand[i]["d_km"])


STRATEGIES = [
    ("S0_min_ul_dl_margin", _pick_s0, False),
    ("S1_uplink_margin", _pick_s1, False),
    ("S2_max_et_rssi", _pick_s2, False),
    ("S3_nearest", _pick_s3, False),
    ("S0_dedup", _pick_s0, True),
    ("S1_dedup", _pick_s1, True),
    ("S2_dedup", _pick_s2, True),
    ("S3_dedup", _pick_s3, True),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-03-01")
    ap.add_argument(
        "--model",
        default=os.environ.get(
            "LORA_ML_MODEL_PATH", "/app/services/ml-service/data/extra_trees_model.joblib"
        ),
    )
    ap.add_argument(
        "--out", type=Path, default=Path("/app/reports/gateway_selection_strategies.json")
    )
    args = ap.parse_args()

    db_url = (os.environ.get("LORA_DB_URL") or os.environ["DATABASE_URL"]).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    model = joblib.load(args.model)
    print(f"Loaded model {args.model}")

    backend = CrcCovlibBackend(
        dem_directory=Path(os.environ["LORA_DEM_DIRECTORY"]),
        surface_dem_directory=(
            Path(os.environ["LORA_SURFACE_DEM_DIRECTORY"])
            if os.environ.get("LORA_SURFACE_DEM_DIRECTORY")
            else None
        ),
        model_version="eval-gw-strategies",
        percent_time=float(os.environ.get("LORA_ITU_PERCENT_TIME", "50")),
        percent_location=float(os.environ.get("LORA_ITU_PERCENT_LOCATION", "50")),
    )
    stage1 = Stage1ItuModel(
        model_version="eval-gw-strategies",
        backend=backend,
        env_profile=resolve_environment_profile(os.environ.get("LORA_ENV_PROFILE", "suburban")),
    )

    sql_gw = """
        SELECT id::text, code, name, ST_Y(location::geometry) AS lat,
               ST_X(location::geometry) AS lon, altitude_m, antenna_height_m,
               antenna_gain_dbi, tx_power_dbm, frequency_mhz,
               rx_antenna_gain_dbi, rx_sensitivity_dbm, noise_floor_dbm
        FROM geo.gateways WHERE is_public = true
    """
    sql_holdout = """
        SELECT DISTINCT ON (t.timestamp, COALESCE(t.device_id, ''))
               ST_Y(t.location::geometry) AS lat, ST_X(t.location::geometry) AS lon,
               t.rssi_dbm AS measured, t.spreading_factor AS sf, t.frequency_mhz AS freq,
               t.serving_gateway_id::text AS actual_gw_id
        FROM ts.survey_training t
        WHERE t.timestamp >= %s::date AND t.timestamp < %s::date
          AND t.serving_gateway_id IS NOT NULL
          AND ST_Y(t.location::geometry) BETWEEN 15.8 AND 16.3
          AND ST_X(t.location::geometry) BETWEEN 107.9 AND 108.5
        ORDER BY t.timestamp, COALESCE(t.device_id, ''), t.rssi_dbm DESC
    """
    with psycopg.connect(db_url) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql_gw)
            gws = [_gw_from_row(g) for g in cur.fetchall()]
            cur.execute(sql_holdout, [args.start, args.end])
            rows = cur.fetchall()
    gw_by_id = {str(g.id): g for g in gws}
    print(f"Loaded {len(gws)} gateways, {len(rows)} holdout rows")

    # Tích lũy lỗi (predicted - measured) cho từng chiến lược + match-vs-actual.
    errs: dict[str, list[float]] = {name: [] for name, _, _ in STRATEGIES}
    errs["REF_actual"] = []
    match: dict[str, int] = {name: 0 for name, _, _ in STRATEGIES}
    n_eval = 0

    for ri, r in enumerate(rows):
        if ri % 25 == 0:
            print(f"  {ri}/{len(rows)}")
        target = Target(
            latitude=float(r["lat"]),
            longitude=float(r["lon"]),
            spreading_factor=int(r["sf"]),
            frequency_mhz=float(r["freq"]),
        )
        measured = float(r["measured"])
        actual_gw = gw_by_id.get(r["actual_gw_id"])
        if actual_gw is None:
            continue

        raw = [
            g
            for g in gws
            if haversine_km(target.latitude, target.longitude, g.latitude, g.longitude)
            < MAX_LINK_KM
        ]
        if not raw:
            continue

        # Bảng per-candidate (full + dedup) — tính 1 lần, dùng lại cho mọi chiến lược.
        full = _build_candidate_table(model, stage1, target, raw)
        dedup = _build_candidate_table(model, stage1, target, list(_dedupe_colocated(raw)))
        if not full or not dedup:
            continue

        # REF: actual gateway end-to-end
        et_actual = _et_rssi(model, target, actual_gw)
        if et_actual is not None:
            errs["REF_actual"].append(et_actual - measured)

        for name, pick, use_dedup in STRATEGIES:
            cand = dedup if use_dedup else full
            idx = pick(cand)
            chosen = cand[idx]
            errs[name].append(chosen["et_rssi"] - measured)
            if chosen["gw"].id == actual_gw.id:
                match[name] += 1
        n_eval += 1

    print(f"\n=== n_eval={n_eval} ===")
    summary = {"n_eval": n_eval, "window": {"start": args.start, "end": args.end}, "strategies": {}}
    header = (
        f"{'strategy':<22} {'n':>4} {'RMSE':>7} {'MAE':>7} {'bias':>7} {'p90':>7} {'match%':>7}"
    )
    print(header)
    print("-" * len(header))
    for name in [*[s[0] for s in STRATEGIES], "REF_actual"]:
        m = _metrics(np.asarray(errs[name]))
        mr = (match[name] / n_eval * 100.0) if (name in match and n_eval) else float("nan")
        summary["strategies"][name] = {**m, "match_pct": None if math.isnan(mr) else mr}
        print(
            f"{name:<22} {m.get('n', 0):>4} {m.get('rmse_db', float('nan')):>7.2f} "
            f"{m.get('mae_db', float('nan')):>7.2f} {m.get('bias_db', float('nan')):>+7.2f} "
            f"{m.get('p90_abs_db', float('nan')):>7.2f} "
            f"{('' if math.isnan(mr) else f'{mr:.1f}'):>7}"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))
    print(f"\nSaved → {args.out}")
    print(
        "\nĐọc kết quả: chọn chiến lược RMSE thấp nhất (gần REF_actual nhất). Nếu "
        "*_dedup < bản không dedup → dedup có ích. Nếu khoảng cách tới REF_actual "
        "còn lớn → phần dư là feature `gateway` one-hot (#3), cần follow-up."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
