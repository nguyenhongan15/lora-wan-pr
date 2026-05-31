"""Empirical check: measured RSSI distribution by distance from gateway.

User challenge (2026-05-31): claim "strong signal within 1-2 km of gateway"
is empirically wrong. Re-verify with ts.survey_training data.
"""

from __future__ import annotations

import os

import psycopg

SQL = """
WITH gw AS (
  SELECT id, code,
         ST_X(location::geometry) AS lon,
         ST_Y(location::geometry) AS lat
  FROM geo.gateways
),
m AS (
  SELECT s.serving_gateway_id,
         s.rssi_dbm AS rssi,
         s.spreading_factor,
         ST_DistanceSphere(
           s.location::geometry,
           ST_SetSRID(ST_MakePoint(g.lon, g.lat), 4326)
         ) / 1000.0 AS d_km
  FROM ts.survey_training s
  JOIN gw g ON g.id = s.serving_gateway_id
)
SELECT
  CASE
    WHEN d_km < 0.25 THEN '0_<0.25km'
    WHEN d_km < 0.5  THEN '1_0.25-0.5km'
    WHEN d_km < 1.0  THEN '2_0.5-1km'
    WHEN d_km < 2.0  THEN '3_1-2km'
    WHEN d_km < 5.0  THEN '4_2-5km'
    WHEN d_km < 10.0 THEN '5_5-10km'
    WHEN d_km < 20.0 THEN '6_10-20km'
    ELSE '7_>20km'
  END AS bin,
  COUNT(*) AS n,
  ROUND(AVG(rssi)::numeric, 1) AS rssi_mean,
  ROUND(percentile_cont(0.5)  WITHIN GROUP (ORDER BY rssi)::numeric, 1) AS rssi_p50,
  ROUND(percentile_cont(0.9)  WITHIN GROUP (ORDER BY rssi)::numeric, 1) AS rssi_p90,
  ROUND(MAX(rssi)::numeric, 1) AS rssi_max,
  ROUND(MIN(d_km)::numeric, 2) AS d_min,
  ROUND(MAX(d_km)::numeric, 2) AS d_max,
  SUM(CASE WHEN rssi >= -100 THEN 1 ELSE 0 END) AS n_strong,
  SUM(CASE WHEN rssi >= -110 AND rssi < -100 THEN 1 ELSE 0 END) AS n_good,
  SUM(CASE WHEN rssi >= -120 AND rssi < -110 THEN 1 ELSE 0 END) AS n_marg,
  SUM(CASE WHEN rssi < -120 THEN 1 ELSE 0 END) AS n_weak
FROM m
WHERE d_km < 50
GROUP BY 1
ORDER BY bin;
"""

dsn = os.environ.get("DATABASE_URL") or "postgresql://lora:lorapw@db:5432/lora"
dsn = dsn.replace("postgresql+psycopg://", "postgresql://")
with psycopg.connect(dsn) as conn, conn.cursor() as cur:
    cur.execute(SQL)
    rows = cur.fetchall()
    cols = [d.name for d in cur.description]

print("\t".join(cols))
for r in rows:
    print("\t".join(str(v) for v in r))

# Also distribution per-gateway, only <2km, to see if at least SOME gw have strong signal close in.
SQL2 = """
WITH gw AS (
  SELECT id, code,
         ST_X(location::geometry) AS lon,
         ST_Y(location::geometry) AS lat
  FROM geo.gateways
),
m AS (
  SELECT g.code AS gw_code,
         s.rssi_dbm AS rssi,
         ST_DistanceSphere(
           s.location::geometry,
           ST_SetSRID(ST_MakePoint(g.lon, g.lat), 4326)
         ) / 1000.0 AS d_km
  FROM ts.survey_training s
  JOIN gw g ON g.id = s.serving_gateway_id
  WHERE s.spreading_factor IS NOT NULL
)
SELECT m.gw_code,
       COUNT(*) FILTER (WHERE d_km < 2.0) AS n_lt2km,
       ROUND(MIN(d_km) FILTER (WHERE d_km < 2.0)::numeric, 2) AS d_min_lt2,
       ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY rssi)
             FILTER (WHERE d_km < 2.0)::numeric, 1) AS rssi_p50_lt2,
       ROUND(MAX(rssi) FILTER (WHERE d_km < 2.0)::numeric, 1) AS rssi_max_lt2,
       ROUND(MIN(d_km)::numeric, 2) AS d_min_overall,
       COUNT(*) AS n_total
FROM m
WHERE d_km < 50
GROUP BY m.gw_code
ORDER BY n_lt2km DESC NULLS LAST;
"""
print("\n=== per-gateway (<2km) ===")
with psycopg.connect(dsn) as conn, conn.cursor() as cur:
    cur.execute(SQL2)
    rows = cur.fetchall()
    cols = [d.name for d in cur.description]
print("\t".join(cols))
for r in rows:
    print("\t".join(str(v) for v in r))
