-- OLS-through-origin fit cho path-loss exponent n từ ts.survey_training.
--
-- Reciprocity: PL(d) ở 923 MHz là as-the-photon-flies, không phụ thuộc direction.
-- Survey records là UPLINK (device→gateway) nhưng n̂ fit ra dùng được cho cả
-- DOWNLINK (gateway→device) trong bidirectional link budget — chỉ Pt/Gt/Gr/sens
-- swap theo hướng, còn PL(d) shared. Refactor bidirectional 2026-05-11 KHÔNG
-- invalidate baseline (n=3.0, σ=23 dB).
--
-- Mô hình: y = 10·(n−2)·log10(d/d0) + ε,  d0 = 100 m
--   y_i = (Pₜ + Gₜ + Gᵣ − Friis(d_i)) − RSSI_measured_i
--   Friis(d) = 32.45 + 20·log10(d_km) + 20·log10(f_MHz)
--   Gᵣ = 0 dBi (target.rx_antenna_gain_dbi không stored trong survey_training)
--   β̂ = Σ(x·y)/Σ(x²),  n̂ = β̂/10 + 2,  σ̂ = sqrt(Σ(y−β̂x)²/(N−1))
--
-- Cách chạy:
--   docker exec -i lora-wan-db psql -U lora_user -d lora_coverage -P pager=off \
--     < scripts/fit_path_loss_exponent.sql
--
-- Scope: Stage 1 calibration CHỈ dùng data Đà Nẵng (lat 15.8–16.3, lon 107.9–108.5).
-- Hải Phòng và các vùng khác KHÔNG vào fit — chỉ dùng cho validation hoặc Stage 2.
-- Quyết định 2026-05-11; xem memory `project_stage1_calibration_scope.md`.
--
-- Aggregate fit có thể bị méo do mixing SF (SF7 chỉ sống gần GW). Script in
-- thêm per-SF breakdown — ưu tiên đọc dòng SF12 (sensitive nhất, range rộng nhất).

\echo === Aggregate fit (toàn bộ SF) ===
WITH joined AS (
    SELECT
        ST_DistanceSphere(s.location::geometry, g.location::geometry) / 1000.0 AS d_km,
        s.rssi_dbm::double precision AS rssi_dbm,
        s.frequency_mhz,
        s.spreading_factor,
        g.tx_power_dbm,
        g.antenna_gain_dbi AS gt_dbi
    FROM ts.survey_training s
    JOIN geo.gateways g ON g.id = s.serving_gateway_id
    WHERE ST_Y(s.location::geometry) BETWEEN 15.8 AND 16.3
      AND ST_X(s.location::geometry) BETWEEN 107.9 AND 108.5
      AND s.serving_gateway_id IS NOT NULL
),
ready AS (
    SELECT
        spreading_factor,
        (log(d_km::numeric / 0.1) / log(10::numeric))::double precision AS x,
        ((tx_power_dbm + gt_dbi - (32.45
            + 20.0*log(d_km::numeric)/log(10::numeric)
            + 20.0*log(frequency_mhz::numeric)/log(10::numeric))) - rssi_dbm)::double precision AS y
    FROM joined
    WHERE d_km > 0.1 AND d_km <= 30.0
),
agg AS (
    SELECT COUNT(*) AS n_obs, SUM(x*y) AS sxy, SUM(x*x) AS sxx, AVG(y) AS y_mean FROM ready
),
fit AS (
    SELECT n_obs, sxy/sxx AS beta_hat, sxx, y_mean FROM agg
),
resid AS (
    SELECT SUM((r.y - f.beta_hat * r.x)^2) AS sse FROM ready r CROSS JOIN fit f
)
SELECT
    f.n_obs,
    round(f.beta_hat::numeric, 4)                                   AS beta_hat,
    round((f.beta_hat/10.0 + 2.0)::numeric, 4)                      AS n_hat,
    round(sqrt(r.sse/(f.n_obs-1))::numeric, 3)                      AS sigma_hat_db,
    round(((f.beta_hat/10.0 + 2.0)
          - 1.96*sqrt(r.sse/(f.n_obs-1))/sqrt(f.sxx)/10.0)::numeric, 4) AS n_lo_95,
    round(((f.beta_hat/10.0 + 2.0)
          + 1.96*sqrt(r.sse/(f.n_obs-1))/sqrt(f.sxx)/10.0)::numeric, 4) AS n_hi_95,
    round(f.y_mean::numeric, 3)                                     AS y_mean_db
FROM fit f CROSS JOIN resid r;

\echo
\echo === Per-SF breakdown (SF12 đáng tin nhất) ===
WITH joined AS (
    SELECT
        ST_DistanceSphere(s.location::geometry, g.location::geometry) / 1000.0 AS d_km,
        s.rssi_dbm::double precision AS rssi_dbm,
        s.frequency_mhz, s.spreading_factor,
        g.tx_power_dbm, g.antenna_gain_dbi AS gt_dbi
    FROM ts.survey_training s
    JOIN geo.gateways g ON g.id = s.serving_gateway_id
    WHERE ST_Y(s.location::geometry) BETWEEN 15.8 AND 16.3
      AND ST_X(s.location::geometry) BETWEEN 107.9 AND 108.5
      AND s.serving_gateway_id IS NOT NULL
),
ready AS (
    SELECT spreading_factor,
        (log(d_km::numeric / 0.1) / log(10::numeric))::double precision AS x,
        ((tx_power_dbm + gt_dbi - (32.45
            + 20.0*log(d_km::numeric)/log(10::numeric)
            + 20.0*log(frequency_mhz::numeric)/log(10::numeric))) - rssi_dbm)::double precision AS y
    FROM joined
    WHERE d_km > 0.1 AND d_km <= 30.0
),
per_sf AS (
    SELECT spreading_factor,
        COUNT(*) AS n_obs,
        SUM(x*y) AS sxy,
        SUM(x*x) AS sxx,
        AVG(y) AS y_mean
    FROM ready GROUP BY spreading_factor
),
per_sf_fit AS (
    SELECT spreading_factor, n_obs, sxy/sxx AS beta_hat, sxx, y_mean FROM per_sf
),
per_sf_resid AS (
    SELECT r.spreading_factor,
           SUM((r.y - f.beta_hat * r.x)^2) AS sse
    FROM ready r
    JOIN per_sf_fit f USING (spreading_factor)
    GROUP BY r.spreading_factor
)
SELECT f.spreading_factor AS sf, f.n_obs,
       round((f.beta_hat/10.0 + 2.0)::numeric, 3) AS n_hat,
       round(sqrt(r.sse/(f.n_obs-1))::numeric, 2) AS sigma_hat_db,
       round(f.y_mean::numeric, 2) AS y_mean_db
FROM per_sf_fit f JOIN per_sf_resid r USING (spreading_factor)
ORDER BY f.spreading_factor;
