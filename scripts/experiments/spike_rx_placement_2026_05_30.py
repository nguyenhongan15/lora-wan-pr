"""Spike: xác định crc-covlib đặt RX ở DTM+h hay DSM+h.

Setup Simulation y hệt precompute_minsf cho gw 7276ff002e0507da. Với mỗi
cell test:
  - DTM = sim.GetTerrainElevation(lat, lon)
  - DSM = sim.GetSurfaceElevation(lat, lon)
  - detail = sim.GenerateReceptionPointDetailedResult(lat, lon)
  - So sánh detail.receiverHeightAMSL_m với (DTM+1.5) vs (DSM+1.5).

Kết luận:
  - |Rx - (DTM+1.5)| < 0.1 → RX đặt ở DTM-relative (đất tự nhiên).
  - |Rx - (DSM+1.5)| < 0.1 → RX đặt ở DSM-relative (tức ở mái nhà nếu cell
    rơi vào building footprint) → đây là root cause của +43 dB d=5-10km.

Test cells chọn quanh gw để cover urban (Hải Châu) + suburb + rural.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "api-service" / "src"))

from crc_covlib import simulation as covlib  # noqa: E402

GW_CODE = "7276ff002e0507da"
GW_LAT = 16.0740935
GW_LON = 108.1524913
ANTENNA_HEIGHT_M = 25.0
FREQ_MHZ = 923.2
RX_HEIGHT_M = 1.5

DEM_DIR = os.environ.get("LORA_DEM_DIRECTORY", "E:/DATN/lora-data/dem")
SURFACE_DEM_DIR = os.environ.get("LORA_SURFACE_DEM_DIRECTORY", "E:/DATN/lora-data/dem-surface")


def _offset_latlon(
    lat: float, lon: float, dist_km: float, bearing_deg: float
) -> tuple[float, float]:
    """Great-circle offset (simple flat-earth — ok cho test scale <15 km)."""
    dlat = dist_km / 111.32 * math.cos(math.radians(bearing_deg))
    dlon = dist_km / (111.32 * math.cos(math.radians(lat))) * math.sin(math.radians(bearing_deg))
    return lat + dlat, lon + dlon


def main() -> int:
    sim = covlib.Simulation()
    sim.SetTransmitterLocation(GW_LAT, GW_LON)
    sim.SetTransmitterHeight(ANTENNA_HEIGHT_M)
    sim.SetTransmitterFrequency(FREQ_MHZ)
    sim.SetTransmitterPower(0.1, covlib.PowerType.EIRP)  # any value — PL không phụ thuộc
    sim.SetReceiverHeightAboveGround(RX_HEIGHT_M)
    sim.SetPropagationModel(covlib.PropagationModel.ITU_R_P_1812)
    sim.SetITURP1812TimePercentage(50.0)
    sim.SetITURP1812LocationPercentage(50.0)
    sim.SetITURP1812SurfaceProfileMethod(
        covlib.P1812SurfaceProfileMethod.P1812_USE_SURFACE_ELEV_DATA
    )
    sim.SetPrimaryTerrainElevDataSource(covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF)
    sim.SetTerrainElevDataSourceDirectory(covlib.TerrainElevDataSource.TERR_ELEV_GEOTIFF, DEM_DIR)
    sim.SetPrimarySurfaceElevDataSource(covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF)
    sim.SetSurfaceElevDataSourceDirectory(
        covlib.SurfaceElevDataSource.SURF_ELEV_GEOTIFF, SURFACE_DEM_DIR
    )
    sim.SetResultType(covlib.ResultType.PATH_LOSS_DB)
    sim.SetTerrainElevDataSamplingResolution(30)

    # Gateway itself + cells dải ra urban/suburb. Bearing tự chọn để cover
    # built-up Hải Châu (W/N), seaside (E), suburb (S).
    test_points = [
        ("gw_itself", GW_LAT, GW_LON),
        ("0.5km_N", *_offset_latlon(GW_LAT, GW_LON, 0.5, 0.0)),
        ("1km_W_built_up", *_offset_latlon(GW_LAT, GW_LON, 1.0, 270.0)),
        ("3km_W", *_offset_latlon(GW_LAT, GW_LON, 3.0, 270.0)),
        ("5km_S", *_offset_latlon(GW_LAT, GW_LON, 5.0, 180.0)),
        ("7km_SW", *_offset_latlon(GW_LAT, GW_LON, 7.0, 225.0)),
        ("10km_W", *_offset_latlon(GW_LAT, GW_LON, 10.0, 270.0)),
    ]

    print(
        f"{'name':<20} {'lat':>10} {'lon':>10} {'DTM':>7} {'DSM':>7} {'gap':>5} "
        f"{'Rx_amsl':>9} {'d_DTM':>6} {'d_DSM':>6} {'verdict':<8} {'PL_dB':>7}"
    )
    print("-" * 120)

    for name, lat, lon in test_points:
        try:
            dtm = sim.GetTerrainElevation(lat, lon, noDataValue=float("nan"))
            dsm = sim.GetSurfaceElevation(lat, lon, noDataValue=float("nan"))
            detail = sim.GenerateReceptionPointDetailedResult(lat, lon)
            rx_amsl = detail.receiverHeightAMSL_m
            pl = detail.pathLoss_dB
            gap = dsm - dtm if math.isfinite(dsm) and math.isfinite(dtm) else float("nan")
            d_dtm = rx_amsl - (dtm + RX_HEIGHT_M) if math.isfinite(dtm) else float("nan")
            d_dsm = rx_amsl - (dsm + RX_HEIGHT_M) if math.isfinite(dsm) else float("nan")
            if math.isfinite(d_dtm) and abs(d_dtm) < 0.5:
                verdict = "DTM"
            elif math.isfinite(d_dsm) and abs(d_dsm) < 0.5:
                verdict = "DSM"
            else:
                verdict = "?"
            print(
                f"{name:<20} {lat:>10.5f} {lon:>10.5f} "
                f"{dtm:>7.2f} {dsm:>7.2f} {gap:>5.1f} "
                f"{rx_amsl:>9.2f} {d_dtm:>6.2f} {d_dsm:>6.2f} {verdict:<8} {pl:>7.2f}"
            )
        except Exception as exc:
            print(f"{name:<20} ERROR: {type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
