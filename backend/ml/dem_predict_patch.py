"""
ml/dem_predict_patch.py — Enrich measurement rows với dữ liệu DEM.

Module này được gọi trong predict.py trước khi build feature DataFrame,
để bổ sung các cột elevation/profile cho những row chưa có.

Tách riêng module này để:
  1. Có thể test/mock độc lập với DEM
  2. Dễ bỏ qua (graceful fallback) khi DEM không có sẵn
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ml.dem import DEMReader

logger = logging.getLogger(__name__)

N_PROFILE_SAMPLES = 20   # số điểm lấy mẫu trên profile TX→RX


def enrich_with_dem(rows: list[dict], dem: "DEMReader | None") -> list[dict]:
    """
    Thêm các trường DEM vào mỗi row nếu chưa có:
      - elev_rx      : độ cao (m) tại vị trí thiết bị
      - elev_tx      : độ cao (m) tại vị trí gateway
      - h_rx         : elev_rx + 1.5 (thiết bị cầm tay)
      - h_tx         : elev_tx + antenna_height_m

    Nếu dem=None hoặc không có tile, trả về rows không thay đổi.
    """
    if dem is None or not dem.tiles:
        logger.debug("[DEMPatch] DEM không có sẵn, bỏ qua enrich")
        return rows

    enriched = []
    for r in rows:
        r = dict(r)   # copy để không mutate input

        try:
            lat_rx = float(r["lat_rx"])
            lng_rx = float(r["lng_rx"])
            lat_tx = float(r["lat_tx"])
            lng_tx = float(r["lng_tx"])

            elev_rx = dem.get_elevation(lat_rx, lng_rx)
            elev_tx = dem.get_elevation(lat_tx, lng_tx)

            device_alt = r.get("device_altitude_m")
            gw_alt     = r.get("gw_altitude_m")
            antenna_h  = float(r.get("antenna_height_m") or 10.0)

            # h_rx (device): ưu tiên GPS MSL từ DB (TS002 LocationInfo.Alt),
            #   fallback DEM elevation + 1.5m AGL (giả định cầm tay).
            if not r.get("h_rx"):
                if device_alt is not None:
                    r["h_rx"] = float(device_alt)
                else:
                    r["h_rx"] = elev_rx + 1.5

            # h_tx (gateway antenna top): ưu tiên gw MSL + antenna_h,
            #   fallback DEM elevation + antenna_h (gateway mount ground-level).
            if not r.get("h_tx"):
                if gw_alt is not None:
                    r["h_tx"] = float(gw_alt) + antenna_h
                else:
                    r["h_tx"] = elev_tx + antenna_h

            r["elev_rx"] = elev_rx
            r["elev_tx"] = elev_tx

        except Exception as e:
            logger.debug("[DEMPatch] Enrich error: %s", e)

        enriched.append(r)

    return enriched


def batch_elevations(
    dem: "DEMReader",
    lats: list[float],
    lngs: list[float],
) -> np.ndarray:
    """
    Lấy elevation cho nhiều điểm (batch) — vectorised per tile.
    Trả về np.ndarray shape (N,).
    """
    result = np.zeros(len(lats), dtype=np.float32)
    for i, (la, lo) in enumerate(zip(lats, lngs)):
        try:
            result[i] = dem.get_elevation(la, lo)
        except Exception:
            result[i] = 0.0
    return result