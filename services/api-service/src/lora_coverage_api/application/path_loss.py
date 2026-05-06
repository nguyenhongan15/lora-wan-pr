"""Path loss models (Stage 1 in v0).

Pure math — không I/O, không infra. Sống ở application layer vì là business logic.

Stage 1: log-distance / Friis hybrid.
  PL(d) = PL(d0) + 10·n·log10(d/d0)
  với PL(d0) free-space tại d0=1m, exponent n theo môi trường.

Khi Stage 2+ ra đời, model sẽ chuyển sang ml-service riêng. Interface giữ nguyên.
"""

from __future__ import annotations

import math
from typing import Protocol

from ..domain.coverage import (
    Confidence,
    ConfidenceMethod,
    CoverageStatus,
    Gateway,
    Prediction,
    Target,
)

# ── Constants (LoRa EU868 conservative defaults) ─────────────────────────
NOISE_FLOOR_DBM_125KHZ = -117.0   # -174 + 10·log10(125e3) + NF(6dB)
SF_SNR_LIMITS_DB: dict[int, float] = {
    7: -7.5,
    8: -10.0,
    9: -12.5,
    10: -15.0,
    11: -17.5,
    12: -20.0,
}
PATH_LOSS_EXPONENT_SUBURBAN = 3.0
SHADOW_FADING_STD_DB = 6.0  # dùng cho confidence interval


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Khoảng cách great-circle (km). Dùng được cho mọi phép tính trên Trái Đất."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _free_space_pl_db(distance_km: float, freq_mhz: float) -> float:
    """Friis free-space path loss. d_km, f_MHz."""
    if distance_km <= 0:
        return 0.0
    # PL = 32.45 + 20·log10(d_km) + 20·log10(f_MHz)
    return 32.45 + 20.0 * math.log10(distance_km) + 20.0 * math.log10(freq_mhz)


def _classify(rssi_dbm: float, snr_db: float, sf: int) -> CoverageStatus:
    sf_limit = SF_SNR_LIMITS_DB[sf]
    if rssi_dbm >= -100.0 and snr_db >= 5.0:
        return CoverageStatus.STRONG
    if snr_db >= sf_limit and rssi_dbm >= -120.0:
        return CoverageStatus.MARGINAL if snr_db < 5.0 else CoverageStatus.STRONG
    if snr_db >= SF_SNR_LIMITS_DB[12]:
        return CoverageStatus.WEAK
    return CoverageStatus.NO_COVERAGE


# 3 dB margin trên SF limit để đảm bảo decode tin cậy (LoRa SNR có jitter).
_SF_MARGIN_DB = 3.0


def _recommend_sf(snr_db: float) -> int:
    """SF nhỏ nhất vẫn decode được với 3 dB margin.

    Theo business-logic.md §4.2 — Layer 2 trả "recommended_sf" cho engineer
    biết nên cấu hình LoRaWAN MAC như thế nào. Không trả SF=7 mặc định khi
    điều kiện thực tế đòi hỏi SF cao hơn — đó là điểm cốt lõi của khuyến nghị.
    """
    for sf in (7, 8, 9, 10, 11, 12):
        if snr_db >= SF_SNR_LIMITS_DB[sf] + _SF_MARGIN_DB:
            return sf
    return 12  # Beyond SF12 limit — vẫn report SF12 (caller xử lý NO_COVERAGE).


class PathLossModel(Protocol):
    """Tất cả model qua các Stage chia sẻ interface này."""

    model_version: str

    def predict(self, target: Target, gateway: Gateway) -> Prediction:
        ...


class Stage1LogDistanceModel:
    """Empirical log-distance — không cần training data."""

    def __init__(self, model_version: str) -> None:
        self.model_version = model_version
        self._exponent = PATH_LOSS_EXPONENT_SUBURBAN

    def predict(self, target: Target, gateway: Gateway) -> Prediction:
        d_km = _haversine_km(
            target.latitude, target.longitude, gateway.latitude, gateway.longitude
        )
        # Tránh chia cho 0 ở khoảng cách cực gần
        d_km_eff = max(d_km, 0.001)

        pl_fs_db = _free_space_pl_db(d_km_eff, target.frequency_mhz)
        # Bù exponent khi distance > d0 = 100m
        d0_km = 0.1
        excess = (
            10.0 * (self._exponent - 2.0) * math.log10(d_km_eff / d0_km)
            if d_km_eff > d0_km
            else 0.0
        )
        pl_db = pl_fs_db + excess

        rssi_dbm = (
            gateway.tx_power_dbm
            + gateway.antenna_gain_dbi
            - pl_db
        )
        snr_db = rssi_dbm - NOISE_FLOOR_DBM_125KHZ

        status = _classify(rssi_dbm, snr_db, target.spreading_factor)

        # Confidence giảm khi distance lớn (uncertainty từ shadow fading).
        # Heuristic: score = exp(-d_km / 20). Tuned lỏng cho v0.
        score = max(0.05, math.exp(-d_km / 20.0))

        return Prediction(
            rssi_dbm=round(rssi_dbm, 2),
            snr_db=round(snr_db, 2),
            coverage_status=status,
            serving_gateway_id=gateway.id,
            confidence=Confidence(score=round(score, 3), method=ConfidenceMethod.EMPIRICAL),
            model_version=self.model_version,
            recommended_sf=_recommend_sf(snr_db),
        )
