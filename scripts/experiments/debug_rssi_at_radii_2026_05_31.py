"""Debug Stage 1 RSSI tại các bán kính cố định từ mỗi gateway.

Quan sát: map hiển thị weak ngay cả quanh gateway. Test xem RSSI tại
{0, 100m, 500m, 1km, 2km, 5km, 10km} từ mỗi gw centroid thực sự bằng bao nhiêu
khi chạy P.1812 + DSM với config production (loc%=10, no-clip).
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path("/app")
sys.path.insert(0, str(REPO_ROOT / "services" / "api-service" / "src"))

DEM_DIR = os.environ.get("LORA_DEM_DIRECTORY", "/data/dem")
SURFACE_DEM_DIR = os.environ.get("LORA_SURFACE_DEM_DIRECTORY", "/data/dem-surface")
STAGE2_MODEL = Path("/tmp/stage2_xgb.joblib")

DEVICE_TX_DBM = 14.0
DEVICE_TX_GAIN = 0.0
DEVICE_HEIGHT_M = 1.5

# Radius offsets (km, east + north) to sample at
RADII_KM = [0.0, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0]


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def offset_deg(lat0: float, dx_km: float, dy_km: float) -> tuple[float, float]:
    """km offset (east, north) → (delta_lon, delta_lat) in degrees."""
    dlat = dy_km / 111.0
    dlon = dx_km / (111.0 * math.cos(math.radians(lat0)))
    return dlon, dlat


def build_sim(gw_row, loc_pct: float):
    from crc_covlib import simulation as covlib

    _code, lat, lon, _ant_g, tx, h, _alt, freq = gw_row
    eirp_dbm = float(tx) + 2.15
    eirp_w = 10.0 ** ((eirp_dbm - 30.0) / 10.0)
    sim = covlib.Simulation()
    sim.SetTransmitterLocation(float(lat), float(lon))
    sim.SetTransmitterHeight(float(h))
    sim.SetTransmitterFrequency(float(freq))
    sim.SetTransmitterPower(eirp_w, covlib.PowerType.EIRP)
    sim.SetReceiverHeightAboveGround(DEVICE_HEIGHT_M)
    sim.SetPropagationModel(covlib.PropagationModel.ITU_R_P_1812)
    sim.SetITURP1812TimePercentage(50.0)
    sim.SetITURP1812LocationPercentage(loc_pct)
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
    return sim


def main():
    dsn = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.execute("""
            SELECT code, ST_Y(location::geometry), ST_X(location::geometry),
                   COALESCE(antenna_gain_dbi, 3.0), COALESCE(tx_power_dbm, 14.0),
                   COALESCE(antenna_height_m, 10.0), COALESCE(altitude_m, 0.0),
                   COALESCE(frequency_mhz, 923.0)
            FROM geo.gateways
            ORDER BY code
        """)
        gws = cur.fetchall()

    import joblib
    import pandas as pd

    model = joblib.load(STAGE2_MODEL)

    print(f"{'gw_code':<20} {'r(km)':<6} | {'PL':>6} {'S1':>7} {'res':>6} {'S2':>7} | {'bin':<6}")

    def bin_of(r):
        if r >= -100:
            return "strong"
        if r >= -110:
            return "good"
        if r >= -120:
            return "marg"
        if r >= -140:
            return "weak"
        return "(<-140)"

    for gw_row in gws:
        code, gw_lat, gw_lon, ant_g, _tx, h, alt, _freq = gw_row
        sim = build_sim(gw_row, 10.0)  # production config: loc%=10
        for r_km in RADII_KM:
            # Sample east of gw (arbitrary direction)
            dlon, _ = offset_deg(gw_lat, r_km, 0.0)
            rx_lat = gw_lat
            rx_lon = gw_lon + dlon
            try:
                pl = sim.GenerateReceptionPointResult(rx_lat, rx_lon)
            except Exception as e:
                print(f"{code:<20} {r_km:<6.2f} | FAIL: {e}")
                continue
            if not math.isfinite(pl):
                print(f"{code:<20} {r_km:<6.2f} | PL=NaN")
                continue
            d_km = _haversine_km(gw_lat, gw_lon, rx_lat, rx_lon)
            s1 = DEVICE_TX_DBM + DEVICE_TX_GAIN + float(ant_g) - pl
            df = pd.DataFrame(
                [
                    {
                        "lat": rx_lat,
                        "lon": rx_lon,
                        "sf": 10.0,
                        "gw_lat": gw_lat,
                        "gw_lon": gw_lon,
                        "distance_km": d_km,
                        "log_distance_km": math.log1p(d_km),
                        "delta_alt_m": float(alt) + float(h),
                    }
                ]
            )
            res = float(model.predict(df)[0])
            s2 = s1 + res  # no clip
            print(
                f"{code:<20} {r_km:<6.2f} | {pl:>6.1f} {s1:>+7.1f} {res:>+6.1f} {s2:>+7.1f} | {bin_of(s2):<6}"
            )
        print()


if __name__ == "__main__":
    main()
