"""
services/sandbox.py — Persona 6 (custom env experimentation).

Phase v3.2 step 2: refactor sang delegate vào rf_predictor (single source of
truth). API surface giữ y nguyên — router và test không cần đổi.

Predict RSSI tại 1 điểm hoặc curve theo bearing, cho user tự nhập:
  - Vị trí TX, RX
  - Tx power, antenna gain
  - Path loss exponent custom (override default theo env) — sandbox-only quirk:
    user chỉnh n để xem curve dB drop thay đổi (giáo dục).
  - SF (cho link budget vs sensitivity)

Tách hoàn toàn khỏi DB → pure function, dễ test, không có side effect.
"""

from __future__ import annotations

from dataclasses import replace

from services.path_loss import PATH_LOSS_EXPONENT
from services.rf_predictor import (
    RFConfig,
    RxParams,
    TxParams,
    predict_radial_profile as _rf_predict_radial,
    predict_rssi_point as _rf_predict_point,
)


def _build_config_with_n_override(
    environment: str,
    spreading_factor: int,
    n_override: float | None,
) -> RFConfig:
    """
    Sandbox cho user override path-loss exponent. rf_predictor không có concept
    này (production dùng calibration). Map override → calibrated branch với
    intercept=PL_AT_1M_DB cố định, sigma=0 (không shadow fading cho sandbox).

    Khi user KHÔNG override → dùng "log-distance" model thường.
    """
    if n_override is None:
        return RFConfig(environment=environment, spreading_factor=spreading_factor)

    return RFConfig(
        environment             = environment,
        spreading_factor        = spreading_factor,
        model                   = "calibrated",
        calibrated_n            = float(n_override),
        calibrated_intercept_db = 40.0,   # Match path_loss.PL_AT_1M_DB default
        calibrated_sigma_db     = 0.0,
        calibration_id          = None,
    )


def predict_point(
    *,
    tx_lat: float, tx_lng: float,
    rx_lat: float, rx_lng: float,
    tx_power_dbm:     float = 14.0,
    antenna_gain_dbi: float = 8.0,
    environment:      str   = "urban",
    path_loss_exponent_override: float | None = None,
    spreading_factor: int   = 9,
) -> dict:
    """
    Predict RSSI tại 1 điểm với cấu hình tuỳ ý.
    Output keys khớp router cũ — không break frontend.
    """
    config = _build_config_with_n_override(
        environment, spreading_factor, path_loss_exponent_override,
    )
    tx = TxParams(
        lat=tx_lat, lng=tx_lng,
        tx_power_dbm=tx_power_dbm, antenna_gain_dbi=antenna_gain_dbi,
    )
    result = _rf_predict_point(tx=tx, rx_lat=rx_lat, rx_lng=rx_lng, config=config)

    # Sandbox surface: thêm pathLossExponent (legacy field cho frontend đồ thị)
    n_used = (
        path_loss_exponent_override
        if path_loss_exponent_override is not None
        else PATH_LOSS_EXPONENT.get(environment, PATH_LOSS_EXPONENT["urban"])
    )
    result["pathLossExponent"] = n_used
    # Drop calibrationId — sandbox không expose calibration concept ra Persona 6
    result.pop("calibrationId", None)
    return result


def predict_radial_profile(
    *,
    tx_lat: float, tx_lng: float,
    bearing_deg: float = 90.0,
    max_distance_m:  int = 5_000,
    n_samples:       int = 50,
    tx_power_dbm:     float = 14.0,
    antenna_gain_dbi: float = 8.0,
    environment:     str   = "urban",
    path_loss_exponent_override: float | None = None,
) -> list[dict]:
    """Predict RSSI dọc 1 hướng để vẽ "RSSI vs distance" cho Persona 6."""
    config = _build_config_with_n_override(
        environment, spreading_factor=9, n_override=path_loss_exponent_override,
    )
    tx = TxParams(
        lat=tx_lat, lng=tx_lng,
        tx_power_dbm=tx_power_dbm, antenna_gain_dbi=antenna_gain_dbi,
    )
    return _rf_predict_radial(
        tx              = tx,
        bearing_deg     = bearing_deg,
        max_distance_m  = max_distance_m,
        n_samples       = n_samples,
        config          = config,
    )
