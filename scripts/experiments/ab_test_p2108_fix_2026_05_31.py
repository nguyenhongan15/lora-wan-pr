"""A/B test fix #1: P.1812+DSM với/không cộng P.2108 clutter.

Hypothesis: P.1812 đang dùng DSM (terrain+building) đã tính diffraction qua nhà thật.
Cộng thêm P.2108 (statistical clutter loss cho "1 trong 2 hoặc cả 2 terminal trong clutter")
khả năng cao double-count loss → over-predict PL.

Test: Replay 337 row holdout Jan-Feb 2026 (Đà Nẵng, SF12), so sánh:
  - A (current): pl = P.1812(DSM) + P.2108
  - B (fix):     pl = P.1812(DSM) only

Metric: bias, σ, RMSE, MAE của (measured_ul_rssi - predicted_ul_rssi) cho 2 cấu hình.
        Per-distance breakdown để xem clutter overcount nặng nhất ở dải nào.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_API_SRC = _REPO_ROOT / "services" / "api-service" / "src"
if str(_API_SRC) not in sys.path:
    sys.path.insert(0, str(_API_SRC))

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Bucket:
    name: str
    n: int
    bias_db: float
    sigma_db: float
    rmse_db: float
    mae_db: float


def _stats(residual: np.ndarray, name: str) -> _Bucket:
    if residual.size == 0:
        return _Bucket(name=name, n=0, bias_db=0.0, sigma_db=0.0, rmse_db=0.0, mae_db=0.0)
    return _Bucket(
        name=name,
        n=int(residual.size),
        bias_db=float(np.mean(residual)),
        sigma_db=float(np.std(residual, ddof=1)) if residual.size > 1 else 0.0,
        rmse_db=float(np.sqrt(np.mean(residual**2))),
        mae_db=float(np.mean(np.abs(residual))),
    )


def _fetch_rows():
    import psycopg

    sql = """
        SELECT t.timestamp,
               ST_Y(t.location::geometry) AS lat,
               ST_X(t.location::geometry) AS lon,
               t.rssi_dbm, t.snr_db, t.spreading_factor,
               t.serving_gateway_id,
               gw.code, gw.name, gw.altitude_m, gw.antenna_height_m,
               gw.antenna_gain_dbi, gw.tx_power_dbm, gw.frequency_mhz,
               ST_Y(gw.location::geometry) AS gw_lat,
               ST_X(gw.location::geometry) AS gw_lon
        FROM ts.survey_training t
        JOIN geo.gateways gw ON gw.id = t.serving_gateway_id
        WHERE t.timestamp >= '2026-01-01'::date AND t.timestamp <= '2026-02-28'::date
          AND ST_Y(t.location::geometry) BETWEEN 15.8 AND 16.3
          AND ST_X(t.location::geometry) BETWEEN 107.9 AND 108.5
          AND t.serving_gateway_id IS NOT NULL
    """
    db_url = os.environ["LORA_DB_URL"]
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )

    from lora_coverage_api.application.itu.backend import GeoPoint, LinkGeometry

    dem_directory = Path(os.environ["LORA_DEM_DIRECTORY"])
    surf = os.environ.get("LORA_SURFACE_DEM_DIRECTORY", "")
    surface_dem_directory = Path(surf) if surf else None
    if surface_dem_directory is None:
        log.error("LORA_SURFACE_DEM_DIRECTORY chưa set — không kiểm tra được fix #1")
        return 1

    # Patch helper: gọi crc-covlib một lần, trả về (pl_p1812_only, pl_p1812_plus_p2108).
    # Tránh chạy Simulation 2 lần — cùng input.
    from crc_covlib import simulation as covlib
    from crc_covlib.helper import itur_p2108

    def both_pls(link: LinkGeometry) -> tuple[float, float]:
        sim = covlib.Simulation()
        sim.SetTransmitterLocation(link.tx.latitude, link.tx.longitude)
        sim.SetTransmitterHeight(link.tx_antenna_height_m)
        sim.SetTransmitterFrequency(link.freq_mhz)
        sim.SetTransmitterPower(0.025, covlib.PowerType.EIRP)
        sim.SetReceiverHeightAboveGround(link.rx_antenna_height_m)
        sim.SetPropagationModel(covlib.PropagationModel.ITU_R_P_1812)
        sim.SetITURP1812TimePercentage(50.0)
        sim.SetITURP1812LocationPercentage(50.0)
        sim.SetITURP1812SurfaceProfileMethod(
            covlib.P1812SurfaceProfileMethod.P1812_USE_SURFACE_ELEV_DATA
        )
        sim.SetPrimaryTerrainElevDataSource(covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF)
        sim.SetTerrainElevDataSourceDirectory(
            covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF, str(dem_directory)
        )
        sim.SetPrimarySurfaceElevDataSource(covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF)
        sim.SetSurfaceElevDataSourceDirectory(
            covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF, str(surface_dem_directory)
        )
        sim.SetResultType(covlib.ResultType.PATH_LOSS_DB)
        sim.SetTerrainElevDataSamplingResolution(30)

        pl_p1812 = sim.GenerateReceptionPointResult(link.rx.latitude, link.rx.longitude)
        if not math.isfinite(pl_p1812):
            raise RuntimeError(f"P.1812 non-finite ({pl_p1812})")

        d_km = _haversine_km(
            link.tx.latitude, link.tx.longitude, link.rx.latitude, link.rx.longitude
        )
        if d_km < 0.25:
            clutter = 0.0
        else:
            clutter = itur_p2108.TerrestrialPathClutterLoss(link.freq_mhz / 1000.0, d_km, 50.0)
        return float(pl_p1812), float(pl_p1812 + clutter)

    rows = _fetch_rows()
    log.info("Fetched %d rows", len(rows))

    # Stage 1 link-budget params for UL: measured rssi = tx_power + tx_gain + gw_rx_gain - pl
    # Vì target.tx_power_dbm = 14 dBm default (survey không lưu real TX power), giả định 14.
    # tx_gain_dbi (device) = 2.15 dBi default. gw_rx_gain = gw.antenna_gain_dbi (None → use TX gain).
    DEVICE_TX_POWER_DBM = 14.0
    DEVICE_TX_GAIN_DBI = 2.15

    residuals_A: list[float] = []  # current: pl with P.2108
    residuals_B: list[float] = []  # fix: pl without P.2108
    distances: list[float] = []
    n_errors = 0

    for i, r in enumerate(rows):
        try:
            tgt_lat, tgt_lon = float(r[1]), float(r[2])
            measured_rssi = float(r[3])
            gw_ant_h = float(r[10])
            gw_gain = float(r[11])
            freq = float(r[13])
            gw_lat = float(r[14])
            gw_lon = float(r[15])

            # UL: tx=device, rx=gateway. tx_antenna_height=device 1.5m AGL.
            # CrcCovlib expects tx_antenna_height_m for the TX (device side here is 1.5).
            # NOTE: backend.basic_transmission_loss_db is reciprocal in dB → swap tx/rx OK.
            # Stage1ItuModel sets tx=gateway, rx=device. For UL link-budget reciprocity OK.
            # Để khớp Stage1ItuModel hiện tại (tx=gw): dùng cùng convention.
            link = LinkGeometry(
                tx=GeoPoint(gw_lat, gw_lon),
                rx=GeoPoint(tgt_lat, tgt_lon),
                tx_antenna_height_m=gw_ant_h,
                rx_antenna_height_m=1.5,
                freq_mhz=freq,
            )
            pl_no_clutter, pl_with_clutter = both_pls(link)

            # UL link-budget (matching compute_link_budget in path_loss.py):
            # rssi = tx_power + tx_gain + rx_gain - pl_db
            # UL: tx_power=device, tx_gain=device, rx_gain=gateway
            ul_rssi_A = DEVICE_TX_POWER_DBM + DEVICE_TX_GAIN_DBI + gw_gain - pl_with_clutter
            ul_rssi_B = DEVICE_TX_POWER_DBM + DEVICE_TX_GAIN_DBI + gw_gain - pl_no_clutter

            residuals_A.append(measured_rssi - ul_rssi_A)
            residuals_B.append(measured_rssi - ul_rssi_B)
            distances.append(_haversine_km(tgt_lat, tgt_lon, gw_lat, gw_lon))

            if (i + 1) % 50 == 0:
                log.info("  ... %d/%d", i + 1, len(rows))
        except Exception as e:
            n_errors += 1
            if n_errors <= 5:
                log.warning("Row error: %r", e)

    arr_A = np.asarray(residuals_A)
    arr_B = np.asarray(residuals_B)
    d_arr = np.asarray(distances)

    overall_A = _stats(arr_A, "A: P.1812+DSM+P.2108 (current)")
    overall_B = _stats(arr_B, "B: P.1812+DSM only (fix #1)")

    bins = [(0, 2), (2, 5), (5, 10), (10, 20), (20, 50)]
    per_dist_A = [_stats(arr_A[(d_arr >= lo) & (d_arr < hi)], f"d=[{lo},{hi})") for lo, hi in bins]
    per_dist_B = [_stats(arr_B[(d_arr >= lo) & (d_arr < hi)], f"d=[{lo},{hi})") for lo, hi in bins]

    # Magnitude của P.2108 contribution (chính là delta PL → delta RSSI ngược dấu)
    p2108_contrib = arr_B - arr_A  # rssi_B - rssi_A = pl_A - pl_B = P.2108_loss (>=0)

    report = {
        "n_samples": int(arr_A.size),
        "n_errors": n_errors,
        "overall": {"A_current": asdict(overall_A), "B_fix1": asdict(overall_B)},
        "p2108_contribution_db": {
            "mean": float(np.mean(p2108_contrib)),
            "std": float(np.std(p2108_contrib, ddof=1)),
            "min": float(np.min(p2108_contrib)),
            "max": float(np.max(p2108_contrib)),
            "median": float(np.median(p2108_contrib)),
        },
        "per_distance": {
            "A_current": [asdict(b) for b in per_dist_A],
            "B_fix1": [asdict(b) for b in per_dist_B],
        },
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
