"""
services/rf_predictor.py — Unified RSSI prediction service.

Phase v3.2 step 2. Single source of truth thay 3 implementation rời rạc:
  - simulator.py     (best-server max grid, no calibration)
  - sandbox.py       (hardcoded log-distance, no calibration)
  - coverage_matrix.py (full pipeline w/ calibration + erf P(covered))

rf_predictor giải quyết: SF gating + sensitivity + classification + calibration
fetch (async) + path-loss dispatch — tất cả pure-functional, deterministic,
hashable config (cache-friendly).

Design (philosophy_of_software_design):
  - Deep module: 3 caller chỉ thấy `predict_*` API + `RFConfig`/`TxParams`/`RxParams`.
    Phía sau ẩn: model registry, calibration cache, sensitivity table, classify map.
  - Pull complexity downward: caller không phải biết "log-distance vs hata vs
    calibrated" branching — rf_predictor tự dispatch.
  - Define errors out of existence: classify(None) trả 'no_data' chứ không raise;
    model name unknown → ValueError tại biên (caller hint sai).

Concurrency: tất cả predict_* là sync pure CPU; resolve_calibration() async vì
phải fetch DB (cache-backed, 5min TTL). Caller (router) gọi resolve trước, rồi
predict — pattern y hệt coverage_matrix.resolve_calibrated_params.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from services.calibration_cache import get_calibrated_params
from services.path_loss import (
    DEFAULT_ANTENNA_GAIN_DBI,
    DEFAULT_FREQ_MHZ,
    DEFAULT_RX_ANTENNA_GAIN_DBI,
    DEFAULT_RX_HEIGHT_M,
    DEFAULT_TX_HEIGHT_M,
    DEFAULT_TX_POWER_DBM,
    RSSI_FLOOR_DBM,
    get_model,
)
from services.terrain_profile import sample_profile as _sample_terrain_profile

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# LoRa sensitivity (dBm) cho BW=125 kHz, CR=4/5 — typical SX1276/8.
# DRY: single source dùng chung sandbox + coverage_matrix.
LORA_SENSITIVITY_DBM: dict[int, float] = {
    7:  -123.0,
    8:  -126.0,
    9:  -129.0,
    10: -132.0,
    11: -134.5,
    12: -137.0,
}

# LoRa Alliance Coverage Verification Test thresholds (dBm).
RSSI_STRONG = -90
RSSI_MEDIUM = -105
RSSI_WEAK   = -120

# Vietnamese verdicts (cho frontend Persona 5 mobile + sandbox).
_VERDICT_VI: dict[str, str] = {
    "strong":  "Sóng mạnh",
    "medium":  "Sóng trung bình",
    "weak":    "Sóng yếu",
    "none":    "Không có sóng",
    "no_data": "Không có dữ liệu",
}


# ─────────────────────────────────────────────────────────────────────────────
# Data classes (frozen → hashable cho cache key compatibility)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TxParams:
    """1 transmitter (gateway giả định hoặc real). Defaults khớp AS923 VN."""
    lat:              float
    lng:              float
    tx_power_dbm:     float = DEFAULT_TX_POWER_DBM
    antenna_gain_dbi: float = DEFAULT_ANTENNA_GAIN_DBI
    antenna_height_m: float = DEFAULT_TX_HEIGHT_M


@dataclass(frozen=True)
class RxParams:
    """End-device nhận (LoRa node). Default: cầm tay 1.5m, antenna 2dBi."""
    height_m:         float = DEFAULT_RX_HEIGHT_M
    antenna_gain_dbi: float = DEFAULT_RX_ANTENNA_GAIN_DBI


@dataclass(frozen=True)
class RFConfig:
    """
    Cấu hình RF chung. model="calibrated" yêu cầu caller gọi
    resolve_calibration() trước để embed snapshot từ DB.
    """
    environment:      str   = "urban"
    frequency_mhz:    float = DEFAULT_FREQ_MHZ
    spreading_factor: int   = 9
    model:            str   = "log-distance"  # log-distance | hata | longley-rice | itm-p2p | calibrated

    # Phase 3: số điểm sample DEM dọc TX→RX cho itm-p2p. NTIA khuyến nghị 50-200.
    itm_profile_n_samples: int = 64

    # Calibrated snapshot — None nếu model != "calibrated".
    calibrated_n:            float | None = None
    calibrated_intercept_db: float | None = None
    calibrated_sigma_db:     float | None = None
    calibration_id:          str   | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Calibration resolver — async (fetch DB cache, embed snapshot)
# ─────────────────────────────────────────────────────────────────────────────

async def resolve_calibration(
    db: AsyncSession,
    config: RFConfig,
    *,
    correlation_id: str | None = None,
) -> RFConfig:
    """
    Nếu config.model='calibrated', fetch params từ calibration_cache và
    embed snapshot vào config. Caller (router) gọi trước predict_*.

    Behavior:
      - model != "calibrated"           → return config gốc, không đụng DB.
      - model == "calibrated", có row   → return new config với calibrated_* set.
      - model == "calibrated", không có → fallback model="log-distance" + log warning.

    Pattern khớp coverage_matrix.resolve_calibrated_params (DRY logic, single test).
    """
    if config.model != "calibrated":
        return config

    params = await get_calibrated_params(db, config.environment)

    if params is None:
        logger.warning(
            "rf_predictor.no_calibration_fallback",
            extra={
                "correlationId": correlation_id,
                "environment":   config.environment,
            },
        )
        return replace(config, model="log-distance")

    return replace(
        config,
        calibration_id          = params["calibration_id"],
        calibrated_n            = params["n_path_loss_exponent"],
        calibrated_intercept_db = params["intercept_db"],
        calibrated_sigma_db     = params["sigma_db"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Path loss dispatch — internal
# ─────────────────────────────────────────────────────────────────────────────

def _path_loss_db(
    distances_m: np.ndarray,
    *,
    config:      RFConfig,
    tx_height_m: float,
    rx_height_m: float,
    tx_coord:    tuple[float, float] | None = None,
    rx_lats:     np.ndarray | None = None,
    rx_lngs:     np.ndarray | None = None,
) -> np.ndarray:
    """
    Vectorized path-loss. Branch:
      - calibrated → PL = intercept + 10·n·log10(d), snapshot từ config.
      - itm-p2p    → DEM profile per (tx,rx) → itm_wrapper.point_to_point_loss.
                     Yêu cầu tx_coord + rx_lats/rx_lngs.
      - khác       → delegate path_loss.get_model() (single source of truth).
    """
    if config.model == "calibrated":
        if config.calibrated_n is None or config.calibrated_intercept_db is None:
            raise ValueError(
                "model='calibrated' nhưng calibrated_n/intercept chưa set; "
                "caller phải gọi resolve_calibration() trước predict_*."
            )
        d = np.maximum(distances_m, 1.0)
        return (
            config.calibrated_intercept_db
            + 10 * config.calibrated_n * np.log10(d)
        )

    if config.model == "itm-p2p":
        if tx_coord is None or rx_lats is None or rx_lngs is None:
            raise ValueError(
                "model='itm-p2p' yêu cầu tx_coord + rx_lats + rx_lngs để build "
                "DEM terrain profile. Caller (point/grid) phải truyền đầy đủ."
            )
        return _itm_p2p_loss(
            tx_coord    = tx_coord,
            rx_lats     = rx_lats,
            rx_lngs     = rx_lngs,
            tx_height_m = tx_height_m,
            rx_height_m = rx_height_m,
            config      = config,
        )

    pl_model = get_model(config.model)
    return pl_model.path_loss_db(
        distances_m,
        environment = config.environment,
        freq_mhz    = config.frequency_mhz,
        tx_height_m = tx_height_m,
        rx_height_m = rx_height_m,
    )


def _itm_p2p_loss(
    *,
    tx_coord:    tuple[float, float],
    rx_lats:     np.ndarray,
    rx_lngs:     np.ndarray,
    tx_height_m: float,
    rx_height_m: float,
    config:      RFConfig,
) -> np.ndarray:
    """
    Phase 3: ITM point-to-point với terrain profile thực từ DEM.
    Loop per RX (ITM không vectorize được — mỗi profile khác nhau).
    DLL nếu có → fallback Python p2p → fallback area-mode (deltaH theo env).
    """
    from ml import itm_wrapper as _itm

    tx_lat, tx_lng = tx_coord
    n = int(rx_lats.shape[0])
    out = np.empty(n, dtype=float)
    n_samples = max(2, int(config.itm_profile_n_samples))
    f = config.frequency_mhz
    h_tx = max(tx_height_m, 1.0)
    h_rx = max(rx_height_m, 0.5)

    use_dll = _itm.DLL_AVAILABLE

    for i in range(n):
        profile = _sample_terrain_profile(
            tx_lat, tx_lng,
            float(rx_lats[i]), float(rx_lngs[i]),
            n_samples=n_samples,
        )
        try:
            if use_dll:
                dbloss, errnum = _itm.point_to_point_loss(profile, h_tx, h_rx, f)
                if errnum < 4:
                    out[i] = float(dbloss)
                    continue
            out[i] = float(_itm.point_to_point_loss_py(profile, h_tx, h_rx, f))
        except Exception as exc:
            logger.debug("itm_p2p_failed", extra={"idx": i, "err": str(exc)})
            out[i] = float(_itm.point_to_point_loss_py(profile, h_tx, h_rx, f))

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — vectorized haversine (DRY shared between point + grid)
# ─────────────────────────────────────────────────────────────────────────────

def _haversine_m_vec(
    lat1: float, lng1: float,
    lat2: np.ndarray, lng2: np.ndarray,
) -> np.ndarray:
    """Scalar (lat1, lng1) vs arrays (lat2, lng2). Sai số <0.5% trong 100km."""
    R  = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lng2 - lng1)
    a  = np.sin(dp / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def _haversine_m_scalar(
    lat1: float, lng1: float, lat2: float, lng2: float,
) -> float:
    R  = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a  = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _project_along_bearing(
    lat0: float, lng0: float, bearing_deg: float, distances_m: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Great-circle destination point cho từng distance — cho radial profile DEM."""
    R   = 6_371_000.0
    br  = math.radians(bearing_deg)
    lat1 = math.radians(lat0)
    lng1 = math.radians(lng0)
    delta = distances_m / R

    sin_lat2 = (
        math.sin(lat1) * np.cos(delta) + math.cos(lat1) * np.sin(delta) * math.cos(br)
    )
    lat2 = np.arcsin(sin_lat2)
    lng2 = lng1 + np.arctan2(
        math.sin(br) * np.sin(delta) * math.cos(lat1),
        np.cos(delta) - math.sin(lat1) * sin_lat2,
    )
    return np.degrees(lat2), np.degrees(lng2)


# ─────────────────────────────────────────────────────────────────────────────
# Public API — link margin + classification
# ─────────────────────────────────────────────────────────────────────────────

def link_margin(rssi_dbm: float, sf: int) -> dict:
    """
    Link budget vs LoRa SF sensitivity.
    Trả: {sensitivityDbm, linkMarginDb, decodeable}.

    Tham chiếu: SX1276 datasheet rev7 Table 13 (BW=125 kHz, CR=4/5).
    """
    sensitivity = LORA_SENSITIVITY_DBM.get(sf, LORA_SENSITIVITY_DBM[9])
    margin      = rssi_dbm - sensitivity
    return {
        "sensitivityDbm": sensitivity,
        "linkMarginDb":   round(margin, 2),
        "decodeable":     margin > 0,
    }


def classify(rssi: float | None) -> tuple[str, str]:
    """
    RSSI (dBm) → (level, verdict tiếng Việt).
    None → ('no_data', 'Không có dữ liệu').
    """
    if rssi is None:                return "no_data", _VERDICT_VI["no_data"]
    if rssi >= RSSI_STRONG:         return "strong",  _VERDICT_VI["strong"]
    if rssi >= RSSI_MEDIUM:         return "medium",  _VERDICT_VI["medium"]
    if rssi >= RSSI_WEAK:           return "weak",    _VERDICT_VI["weak"]
    return "none", _VERDICT_VI["none"]


# ─────────────────────────────────────────────────────────────────────────────
# Public API — RSSI predictions
# ─────────────────────────────────────────────────────────────────────────────

def predict_rssi_point(
    *,
    tx:     TxParams,
    rx_lat: float,
    rx_lng: float,
    rx:     RxParams = RxParams(),
    config: RFConfig = RFConfig(),
) -> dict:
    """
    Scalar prediction tại 1 điểm. Trả dict đầy đủ cho frontend (sandbox + coverage):
      predictedRssiDbm, pathLossDb, distanceM, sensitivityDbm, linkMarginDb,
      decodeable, level, verdict, calibrationId.
    """
    dist_m = max(_haversine_m_scalar(tx.lat, tx.lng, rx_lat, rx_lng), 1.0)
    pl_arr = _path_loss_db(
        np.array([dist_m]),
        config      = config,
        tx_height_m = tx.antenna_height_m,
        rx_height_m = rx.height_m,
        tx_coord    = (tx.lat, tx.lng),
        rx_lats     = np.array([rx_lat]),
        rx_lngs     = np.array([rx_lng]),
    )
    pl    = float(pl_arr[0])
    rssi  = tx.tx_power_dbm + tx.antenna_gain_dbi + rx.antenna_gain_dbi - pl
    margin = link_margin(rssi, config.spreading_factor)
    level, verdict = classify(rssi)

    return {
        "predictedRssiDbm": round(rssi, 2),
        "pathLossDb":       round(pl, 2),
        "distanceM":        round(dist_m, 1),
        "sensitivityDbm":   margin["sensitivityDbm"],
        "linkMarginDb":     margin["linkMarginDb"],
        "decodeable":       margin["decodeable"],
        "level":            level,
        "verdict":          verdict,
        "calibrationId":    config.calibration_id,
    }


def predict_combined_rssi(
    *,
    transmitters: list[TxParams],
    rx_lats:      np.ndarray,
    rx_lngs:      np.ndarray,
    rx:           RxParams = RxParams(),
    config:       RFConfig = RFConfig(),
) -> np.ndarray:
    """
    Best-server max combining cho grid prediction (LoRa star topology — gateway
    tốt nhất nhận packet thay device).

    Returns: array shape (len(rx_lats),) RSSI dBm.
    """
    best = np.full(len(rx_lats), -200.0, dtype=float)
    for tx in transmitters:
        d = np.maximum(_haversine_m_vec(tx.lat, tx.lng, rx_lats, rx_lngs), 1.0)
        pl = _path_loss_db(
            d,
            config      = config,
            tx_height_m = tx.antenna_height_m,
            rx_height_m = rx.height_m,
            tx_coord    = (tx.lat, tx.lng),
            rx_lats     = rx_lats,
            rx_lngs     = rx_lngs,
        )
        rssi = tx.tx_power_dbm + tx.antenna_gain_dbi + rx.antenna_gain_dbi - pl
        best = np.maximum(best, rssi)
    return best


def predict_radial_profile(
    *,
    tx:             TxParams,
    bearing_deg:    float = 90.0,
    max_distance_m: int   = 5_000,
    n_samples:      int   = 50,
    rx:             RxParams = RxParams(),
    config:         RFConfig = RFConfig(),
) -> list[dict]:
    """
    Curve "RSSI vs distance" dọc bearing. Dùng cho biểu đồ 2D (sandbox).

    Note: bearing không ảnh hưởng path loss (đối xứng radial trong các model
    hiện hỗ trợ); giữ tham số để frontend label trục, và để sau này đụng terrain
    p2p mode (Phase 3) bearing sẽ matter.
    """
    distances = np.linspace(50.0, float(max_distance_m), n_samples)

    # Phase 3: cho itm-p2p, synthesize rx coord dọc bearing để có terrain profile
    # thật. Các model khác bỏ qua coord (đối xứng radial).
    rx_lats_arr, rx_lngs_arr = _project_along_bearing(
        tx.lat, tx.lng, bearing_deg, distances,
    )
    pl = _path_loss_db(
        distances,
        config      = config,
        tx_height_m = tx.antenna_height_m,
        rx_height_m = rx.height_m,
        tx_coord    = (tx.lat, tx.lng),
        rx_lats     = rx_lats_arr,
        rx_lngs     = rx_lngs_arr,
    )
    rssi = tx.tx_power_dbm + tx.antenna_gain_dbi + rx.antenna_gain_dbi - pl
    return [
        {"distanceM": float(d), "rssiDbm": round(float(r), 2)}
        for d, r in zip(distances, rssi)
    ]


# Re-export RSSI floor cho caller cần (compute_auto_bbox, etc).
__all__ = [
    "LORA_SENSITIVITY_DBM",
    "RSSI_FLOOR_DBM",
    "RSSI_STRONG", "RSSI_MEDIUM", "RSSI_WEAK",
    "TxParams", "RxParams", "RFConfig",
    "resolve_calibration",
    "predict_rssi_point", "predict_combined_rssi", "predict_radial_profile",
    "link_margin", "classify",
]
