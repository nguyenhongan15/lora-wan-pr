"""
services/path_loss.py — Pluggable path loss models for coverage simulation.

Models:
  - LogDistanceModel : PL = PL₀ + 10n·log10(d), n từ env class (Rappaport).
  - HataModel        : Okumura-Hata (1980), tốt cho urban/suburban/rural ở 868 MHz.
  - LongleyRiceModel : ITM v1.2.2 area mode — chính xác nhất, đặc biệt địa hình
                       phức tạp (đồi núi, rừng, ven biển). Dùng ITM122.dll khi có,
                       tự fallback sang pure-Python xấp xỉ nếu DLL chưa compile.

Backward compat: API cũ (`predict_rssi_at`, `predict_combined_rssi`,
`compute_auto_bbox`, `Transmitter`) giữ signature, default `model="log-distance"`.

References:
  - Hata, M. (1980). Empirical formula for propagation loss in land mobile radio.
  - Rappaport, T.S. (2002). Wireless Communications: Principles and Practice.
  - NTIA TM-10-467 (2010). A Summary of the Longley-Rice Model.
  - LoRaWAN TS001 §5.1: -135 dBm sensitivity floor (SF12/125kHz).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from services.grid import meters_to_deg_lat, meters_to_deg_lng

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Path loss exponent theo môi trường (Rappaport)
PATH_LOSS_EXPONENT = {
    "urban":    3.5,
    "suburban": 3.0,
    "rural":    2.5,
    "forest":   3.8,
    "coastal":  2.7,
    "mountain": 3.2,
}

DEFAULT_ANTENNA_GAIN_DBI  = 8.0
DEFAULT_RX_ANTENNA_GAIN_DBI = 2.0   # device antenna typical (omni 2-3 dBi)
DEFAULT_TX_POWER_DBM      = 14.0    # EU868 max (ETSI EN 300 220)
DEFAULT_TX_HEIGHT_M       = 30.0    # rooftop điển hình + Hata sweet-spot floor
DEFAULT_RX_HEIGHT_M       = 1.5     # cầm tay (Hata MS height range 1-10m)
DEFAULT_FREQ_MHZ          = 923.0   # AS923 (Việt Nam)
PL_AT_1M_DB               = 40.0    

# Demodulation floor — LoRaWAN SF12/125kHz, region-agnostic worst case.
RSSI_FLOOR_DBM            = -137.0


# ─────────────────────────────────────────────────────────────────────────────
# Protocol — pluggable path loss models
# ─────────────────────────────────────────────────────────────────────────────

@runtime_checkable
class PathLossModel(Protocol):
    """
    Path loss model interface. Implement này để thêm Cost-231, Longley-Rice,
    ITU-R P.1812, hay model do project tự calibrate.
    """
    name: str

    def path_loss_db(
        self,
        distance_m: np.ndarray,
        *,
        environment:  str   = "urban",
        freq_mhz:     float = DEFAULT_FREQ_MHZ,
        tx_height_m:  float = DEFAULT_TX_HEIGHT_M,
        rx_height_m:  float = DEFAULT_RX_HEIGHT_M,
    ) -> np.ndarray: ...


# ─────────────────────────────────────────────────────────────────────────────
# Model: Log-distance
# ─────────────────────────────────────────────────────────────────────────────

class LogDistanceModel:
    """
    Log-distance path loss: PL(d) = PL₀ + 10·n·log10(d).

    Đơn giản, ổn định mọi distance/freq/height. n từ PATH_LOSS_EXPONENT.
    Dùng làm default + baseline cho calibration.
    """
    name = "log-distance"

    def path_loss_db(
        self,
        distance_m: np.ndarray,
        *,
        environment:  str   = "urban",
        freq_mhz:     float = DEFAULT_FREQ_MHZ,    # ignored (model không dùng)
        tx_height_m:  float = DEFAULT_TX_HEIGHT_M,  # ignored
        rx_height_m:  float = DEFAULT_RX_HEIGHT_M,  # ignored
    ) -> np.ndarray:
        n = PATH_LOSS_EXPONENT.get(environment, PATH_LOSS_EXPONENT["urban"])
        d = np.maximum(distance_m, 1.0)   # tránh log(0)
        return PL_AT_1M_DB + 10 * n * np.log10(d)


# ─────────────────────────────────────────────────────────────────────────────
# Model: Okumura-Hata
# ─────────────────────────────────────────────────────────────────────────────

class HataModel:
    """
    Okumura-Hata path loss (1980).

    Validity:
      - 150 ≤ f ≤ 1500 MHz   (LoRa 923 MHz ✓)
      - 30  ≤ h_b ≤ 200 m    (rooftop typical; sai số ±5 dB nếu < 30m)
      - 1   ≤ h_m ≤ 10 m
      - 1   ≤ d   ≤ 20 km

    Hata gốc chỉ phân 3 env: urban / suburban / rural-open. Project có 6 env →
    map xuống 3 class gần nhất qua HATA_ENV_MAP. Khi cần model riêng cho
    forest/coastal/mountain, calibrate offset từ measurement (Phase 1.5).

    Distance < 1 km: để Hata extrapolate (sai số ~4 dB so free-space @ 10m,
    chấp nhận được). Không fallback log-distance vì tạo discontinuity ~19 dB
    tại d=1km giữa hai model.
    """
    name = "hata"

    MIN_VALID_TX_HEIGHT_M = 30.0

    # 6-env project → 3-env Hata
    HATA_ENV_MAP = {
        "urban":    "urban",
        "suburban": "suburban",
        "rural":    "rural",
        "forest":   "urban",      # tán cây dày = obstruction cao
        "coastal":  "suburban",   # mix open + low building
        "mountain": "urban",      # terrain reflection
    }

    def path_loss_db(
        self,
        distance_m: np.ndarray,
        *,
        environment:  str   = "urban",
        freq_mhz:     float = DEFAULT_FREQ_MHZ,
        tx_height_m:  float = DEFAULT_TX_HEIGHT_M,
        rx_height_m:  float = DEFAULT_RX_HEIGHT_M,
    ) -> np.ndarray:
        # Cảnh báo nếu ngoài validity (debug-level, không spam logs)
        if tx_height_m < self.MIN_VALID_TX_HEIGHT_M:
            logger.debug(
                "hata.tx_height_below_validity",
                extra={"txHeightM": tx_height_m,
                       "expectedDeviationDb": "±5"},
            )

        # Clamp d ≥ 1m: tránh log(0) hoặc PL âm ở near-field
        d_km    = np.maximum(distance_m, 1.0) / 1000.0
        log_f   = math.log10(freq_mhz)
        log_h_b = math.log10(max(tx_height_m, 1.0))

        # Mobile station correction (small/medium city — generic LoRa device)
        a_hm = (1.1 * log_f - 0.7) * rx_height_m - (1.56 * log_f - 0.8)

        # Urban baseline (Hata Eq. 1)
        pl_urban = (
            69.55
            + 26.16 * log_f
            - 13.82 * log_h_b
            - a_hm
            + (44.9 - 6.55 * log_h_b) * np.log10(d_km)
        )

        hata_env = self.HATA_ENV_MAP.get(environment, "urban")
        if hata_env == "suburban":
            log_f_28 = math.log10(freq_mhz / 28.0)
            return pl_urban - 2 * log_f_28 ** 2 - 5.4
        if hata_env == "rural":
            return pl_urban - 4.78 * log_f ** 2 + 18.33 * log_f - 40.94
        return pl_urban


# ─────────────────────────────────────────────────────────────────────────────
# Model: Longley-Rice (ITM v1.2.2)
# ─────────────────────────────────────────────────────────────────────────────

class LongleyRiceModel:
    """
    Longley-Rice Irregular Terrain Model (ITM) — area-mode path loss.

    Sử dụng terrain irregularity parameter (deltaH) đặc trưng theo môi trường.
    Chính xác hơn Hata ~8-15 dB ở địa hình phức tạp (đồi, rừng, ven biển).

    Chế độ hoạt động:
      - DLL mode   : Gọi ITM122.dll — kết quả chuẩn NTIA (±3 dB).
      - Python mode: Pure-Python fallback — xấp xỉ ITM (±8-12 dB), luôn hoạt động.

    Validity (cả hai mode):
      - 20 MHz ≤ f ≤ 20 GHz   (LoRa 923 MHz ✓)
      - 1 m ≤ h_tx ≤ 3000 m
      - 0.5 m ≤ h_rx ≤ 3000 m
      - 0.1 km ≤ d ≤ 2000 km (ITM), 0.1-100 km (Python mode)

    deltaH (m) theo môi trường — terrain irregularity parameter:
      Flat coastal (5), Rural flat (10), Suburban (20), Urban (30),
      Forest (50), Mountain (120)
    """

    name = "longley-rice"

    # Terrain irregularity (m) theo môi trường — chuẩn NTIA area mode
    DELTA_H_MAP: dict[str, float] = {
        "urban":    30.0,   # đô thị, tòa nhà + mặt đất không đều
        "suburban": 20.0,   # khu dân cư, nhà thấp
        "rural":    10.0,   # đồng bằng, đồng ruộng (Mekong Delta)
        "forest":   50.0,   # rừng, tán cây cao + địa hình không đều
        "coastal":   5.0,   # ven biển, địa hình rất bằng phẳng
        "mountain": 120.0,  # Tây Nguyên / miền núi Bắc Bộ
    }

    def __init__(self) -> None:
        # Lazy import để tránh circular + handle trường hợp module chưa tồn tại
        try:
            from ml import itm_wrapper as _itm
            self._itm = _itm
        except Exception:
            self._itm = None
        self._fallback = HataModel()

    def path_loss_db(
        self,
        distance_m: np.ndarray,
        *,
        environment:  str   = "urban",
        freq_mhz:     float = DEFAULT_FREQ_MHZ,
        tx_height_m:  float = DEFAULT_TX_HEIGHT_M,
        rx_height_m:  float = DEFAULT_RX_HEIGHT_M,
    ) -> np.ndarray:
        delta_h = self.DELTA_H_MAP.get(environment, 30.0)
        d_arr   = np.atleast_1d(np.asarray(distance_m, dtype=float))
        result  = np.empty_like(d_arr)

        for i, d_m in enumerate(d_arr):
            result[i] = self._predict_one(
                d_m, delta_h, freq_mhz, tx_height_m, rx_height_m, environment
            )

        return result

    def _predict_one(
        self,
        d_m: float,
        delta_h: float,
        freq_mhz: float,
        tx_height_m: float,
        rx_height_m: float,
        environment: str,
    ) -> float:
        """Path loss tại một điểm — DLL nếu có, Python fallback nếu không."""
        itm = self._itm
        if itm is not None and itm.DLL_AVAILABLE:
            try:
                dbloss, errnum = itm.area_mode_loss(
                    dist_km=max(d_m, 1.0) / 1000.0,
                    delta_h=delta_h,
                    tht_m=max(tx_height_m, 1.0),
                    rht_m=max(rx_height_m, 0.5),
                    frq_mhz=freq_mhz,
                )
                if errnum < 4:   # 0=OK, 1=note, 2=warning — vẫn dùng được
                    return float(dbloss)
            except Exception as exc:
                logger.debug("itm_dll_call_failed", extra={"err": str(exc)})

        # Python fallback
        if itm is not None:
            try:
                return itm.area_mode_loss_py(
                    dist_km=max(d_m, 1.0) / 1000.0,
                    delta_h=delta_h,
                    tht_m=max(tx_height_m, 1.0),
                    rht_m=max(rx_height_m, 0.5),
                    frq_mhz=freq_mhz,
                )
            except Exception as exc:
                logger.debug("itm_py_fallback_failed", extra={"err": str(exc)})

        # Last resort: Hata
        return float(self._fallback.path_loss_db(
            np.array([d_m]),
            environment=environment,
            freq_mhz=freq_mhz,
            tx_height_m=tx_height_m,
            rx_height_m=rx_height_m,
        )[0])


# ─────────────────────────────────────────────────────────────────────────────
# Model registry — singleton instances (immutable, cheap to share)
# ─────────────────────────────────────────────────────────────────────────────

_MODELS: dict[str, PathLossModel] = {
    "log-distance":  LogDistanceModel(),
    "hata":          HataModel(),
    "longley-rice":  LongleyRiceModel(),
}

DEFAULT_MODEL = "log-distance"


def auto_select_model(environment: str, tx_height_m: float) -> str:
    """
    Chọn path-loss model dựa trên môi trường + độ cao anten.

    Rule:
      - mountain / forest / coastal → longley-rice (terrain irregularity quan trọng)
      - urban / suburban / rural + height ≥ 30m → hata (validity sweet-spot)
      - còn lại (anten thấp) → log-distance (Hata sai số ±5 dB khi h_b < 30m)

    itm-p2p không auto-pick (cần DEM, chậm) — power-user opt-in qua API field `model`.
    """
    if environment in ("mountain", "forest", "coastal"):
        return "longley-rice"
    if tx_height_m >= HataModel.MIN_VALID_TX_HEIGHT_M and environment in ("urban", "suburban", "rural"):
        return "hata"
    return "log-distance"


def get_model(name: str) -> PathLossModel:
    """Lookup model by name. Raise ValueError nếu không tồn tại."""
    try:
        return _MODELS[name]
    except KeyError:
        raise ValueError(
            f"Unknown path loss model '{name}'. Available: {list(_MODELS)}"
        ) from None


def list_models() -> list[str]:
    """List tên model có sẵn (dùng cho API discovery)."""
    return list(_MODELS)


# ─────────────────────────────────────────────────────────────────────────────
# Transmitter dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Transmitter:
    """Gateway giả định cho simulator. Default antenna_height = 30m (Hata sweet-spot)."""
    lat:              float
    lng:              float
    tx_power_dbm:     float = DEFAULT_TX_POWER_DBM
    antenna_gain_dbi: float = DEFAULT_ANTENNA_GAIN_DBI
    antenna_height_m: float = DEFAULT_TX_HEIGHT_M


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — vectorized haversine
# ─────────────────────────────────────────────────────────────────────────────

def _haversine_m(
    lat1: float, lng1: float,
    lat2: np.ndarray, lng2: np.ndarray,
) -> np.ndarray:
    """Vectorized haversine — scalar (lat1, lng1) vs arrays (lat2, lng2)."""
    R  = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lng2 - lng1)
    a  = np.sin(dp / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


# ─────────────────────────────────────────────────────────────────────────────
# Public API — RSSI predictions
# ─────────────────────────────────────────────────────────────────────────────

def predict_rssi_at(
    tx_lat: float, tx_lng: float,
    rx_lats: np.ndarray, rx_lngs: np.ndarray,
    *,
    tx_power_dbm:        float = DEFAULT_TX_POWER_DBM,
    antenna_gain_dbi:    float = DEFAULT_ANTENNA_GAIN_DBI,
    rx_antenna_gain_dbi: float = DEFAULT_RX_ANTENNA_GAIN_DBI,
    antenna_height_m:    float = DEFAULT_TX_HEIGHT_M,
    environment:         str   = "urban",
    freq_mhz:            float = DEFAULT_FREQ_MHZ,
    rx_height_m:         float = DEFAULT_RX_HEIGHT_M,
    model:               str   = DEFAULT_MODEL,
) -> np.ndarray:
    """
    RSSI (dBm) tại các điểm rx từ 1 transmitter, dùng path loss model chỉ định.

    Backward-compatible: signature cũ (không có model/freq/height/...) vẫn dùng được.
    """
    pl_model = get_model(model)
    dist_m   = _haversine_m(tx_lat, tx_lng, rx_lats, rx_lngs)
    dist_m   = np.maximum(dist_m, 1.0)

    pl = pl_model.path_loss_db(
        dist_m,
        environment = environment,
        freq_mhz    = freq_mhz,
        tx_height_m = antenna_height_m,
        rx_height_m = rx_height_m,
    )
    return tx_power_dbm + antenna_gain_dbi + rx_antenna_gain_dbi - pl


def predict_combined_rssi(
    transmitters: list[Transmitter],
    rx_lats: np.ndarray, rx_lngs: np.ndarray,
    environment:  str   = "urban",
    *,
    freq_mhz:            float = DEFAULT_FREQ_MHZ,
    rx_height_m:         float = DEFAULT_RX_HEIGHT_M,
    rx_antenna_gain_dbi: float = DEFAULT_RX_ANTENNA_GAIN_DBI,
    model:               str   = DEFAULT_MODEL,
) -> np.ndarray:
    """
    Multiple transmitters → mỗi điểm grid lấy RSSI MAX (best-server).
    Khớp mô hình LoRa: gateway tốt nhất nhận packet thay device.
    """
    best = np.full(len(rx_lats), -200.0, dtype=float)
    for tx in transmitters:
        rssi = predict_rssi_at(
            tx.lat, tx.lng, rx_lats, rx_lngs,
            tx_power_dbm        = tx.tx_power_dbm,
            antenna_gain_dbi    = tx.antenna_gain_dbi,
            rx_antenna_gain_dbi = rx_antenna_gain_dbi,
            antenna_height_m    = tx.antenna_height_m,
            environment         = environment,
            freq_mhz            = freq_mhz,
            rx_height_m         = rx_height_m,
            model               = model,
        )
        best = np.maximum(best, rssi)
    return best


def compute_auto_bbox(
    transmitters: list[Transmitter],
    environment: str = "urban",
    *,
    freq_mhz:            float = DEFAULT_FREQ_MHZ,
    rx_height_m:         float = DEFAULT_RX_HEIGHT_M,
    rx_antenna_gain_dbi: float = DEFAULT_RX_ANTENNA_GAIN_DBI,
    model:               str   = DEFAULT_MODEL,
) -> tuple[float, float, float, float]:
    """
    Tính bbox bao trùm vùng phủ lý thuyết (RSSI ≥ RSSI_FLOOR_DBM) của tất cả tx.

    Numerical binary search (~12-bit precision, ~12m resolution trên 50km) thay
    closed-form — works với mọi PathLossModel, không chỉ log-distance.

    Returns: (min_lat, max_lat, min_lng, max_lng)
    """
    pl_model = get_model(model)

    min_lat, max_lat = float("inf"), float("-inf")
    min_lng, max_lng = float("inf"), float("-inf")

    for tx in transmitters:
        # Tìm d_max sao cho PL(d_max) = link_budget_threshold
        target_pl = (
            tx.tx_power_dbm + tx.antenna_gain_dbi
            + rx_antenna_gain_dbi - RSSI_FLOOR_DBM
        )

        lo, hi = 1.0, 50_000.0
        for _ in range(40):  # ~12-bit precision
            mid = (lo + hi) / 2
            pl_mid = pl_model.path_loss_db(
                np.array([mid]),
                environment = environment,
                freq_mhz    = freq_mhz,
                tx_height_m = tx.antenna_height_m,
                rx_height_m = rx_height_m,
            )[0]
            if pl_mid < target_pl:
                lo = mid    # còn margin → tăng d
            else:
                hi = mid    # vượt budget → giảm d
        d_max_m = lo

        d_lat = meters_to_deg_lat(d_max_m)
        d_lng = meters_to_deg_lng(d_max_m, tx.lat)

        min_lat = min(min_lat, tx.lat - d_lat)
        max_lat = max(max_lat, tx.lat + d_lat)
        min_lng = min(min_lng, tx.lng - d_lng)
        max_lng = max(max_lng, tx.lng + d_lng)

    return min_lat, max_lat, min_lng, max_lng