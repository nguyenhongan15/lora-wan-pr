-- Validate Stage 1 (Friis + log-distance excess, SUBURBAN_PROFILE) trên data Đà Nẵng.
--
-- Replay đúng công thức của Stage1LogDistanceModel.predict():
--   d_eff   = max(d_km, 0.001)
--   PL_fs   = 32.45 + 20·log10(d_eff) + 20·log10(923)        -- f_MHz mặc định 923
--   excess  = 10·(3.0 − 2)·log10(d_eff/0.1)  nếu d_eff > 0.1, else 0
--   RSSI_p  = tx_power + antenna_gain + 0  − (PL_fs + excess)  -- Gᵣ=0 default
--
-- Pair: dùng serving_gateway_id đã ghi trong survey (không re-select GW) —
-- validate riêng phần path-loss model, không trộn với candidate selection.
-- Scope: Đà Nẵng bbox 15.8–16.3 / 107.9–108.5 (memory `project_stage1_calibration_scope`).
--
-- Cách chạy:
--   docker exec -i lora-wan-db psql -U lora_user -d lora_coverage -P pager=off \
--     < scripts/validate_stage1_danang.sql

\set n_value 3.0

\echo === Overall (toàn bộ records, mọi SF, mọi khoảng cách) ===
WITH joined AS (
    SELECT
        ST_DistanceSphere(s.location::geometry, g.location::geometry) / 1000.0 AS d_km,
        s.rssi_dbm::double precision AS rssi_meas,
        s.spreading_factor,
        g.tx_power_dbm,
        g.antenna_gain_dbi
    FROM ts.survey_training s
    JOIN geo.gateways g ON g.id = s.serving_gateway_id
    WHERE ST_Y(s.location::geometry) BETWEEN 15.8 AND 16.3
      AND ST_X(s.location::geometry) BETWEEN 107.9 AND 108.5
      AND s.serving_gateway_id IS NOT NULL
),
predicted AS (
    SELECT
        d_km, rssi_meas, spreading_factor,
        tx_power_dbm + antenna_gain_dbi - (
            32.45
            + 20.0 * log(GREATEST(d_km, 0.001)::numeric) / log(10::numeric)
            + 20.0 * log(923.0::numeric) / log(10::numeric)
            + CASE WHEN d_km > 0.1
                THEN 10.0 * (:n_value - 2.0) * log(d_km::numeric / 0.1) / log(10::numeric)
                ELSE 0.0 END
        )::double precision AS rssi_pred
    FROM joined
)
SELECT
    COUNT(*)                                                   AS n,
    round(SQRT(AVG((rssi_pred - rssi_meas)^2))::numeric, 2)    AS rmse_db,
    round(AVG(ABS(rssi_pred - rssi_meas))::numeric, 2)         AS mae_db,
    round(AVG(rssi_pred - rssi_meas)::numeric, 2)              AS bias_db,
    round(STDDEV_SAMP(rssi_pred - rssi_meas)::numeric, 2)      AS std_resid_db,
    round(MIN(rssi_pred - rssi_meas)::numeric, 1)              AS min_resid,
    round(MAX(rssi_pred - rssi_meas)::numeric, 1)              AS max_resid
FROM predicted;

\echo
\echo === Per-SF breakdown ===
WITH joined AS (
    SELECT
        ST_DistanceSphere(s.location::geometry, g.location::geometry) / 1000.0 AS d_km,
        s.rssi_dbm::double precision AS rssi_meas,
        s.spreading_factor,
        g.tx_power_dbm, g.antenna_gain_dbi
    FROM ts.survey_training s
    JOIN geo.gateways g ON g.id = s.serving_gateway_id
    WHERE ST_Y(s.location::geometry) BETWEEN 15.8 AND 16.3
      AND ST_X(s.location::geometry) BETWEEN 107.9 AND 108.5
      AND s.serving_gateway_id IS NOT NULL
),
predicted AS (
    SELECT
        spreading_factor,
        tx_power_dbm + antenna_gain_dbi - (
            32.45 + 20.0*log(GREATEST(d_km, 0.001)::numeric)/log(10::numeric)
                  + 20.0*log(923.0::numeric)/log(10::numeric)
            + CASE WHEN d_km > 0.1
                THEN 10.0 * (:n_value - 2.0) * log(d_km::numeric/0.1)/log(10::numeric)
                ELSE 0.0 END
        )::double precision AS rssi_pred,
        rssi_meas
    FROM joined
)
SELECT
    spreading_factor AS sf,
    COUNT(*)                                                AS n,
    round(SQRT(AVG((rssi_pred - rssi_meas)^2))::numeric, 2) AS rmse_db,
    round(AVG(ABS(rssi_pred - rssi_meas))::numeric, 2)      AS mae_db,
    round(AVG(rssi_pred - rssi_meas)::numeric, 2)           AS bias_db
FROM predicted
GROUP BY spreading_factor
ORDER BY spreading_factor;

\echo
\echo === Per-distance bucket ===
WITH joined AS (
    SELECT
        ST_DistanceSphere(s.location::geometry, g.location::geometry) / 1000.0 AS d_km,
        s.rssi_dbm::double precision AS rssi_meas,
        g.tx_power_dbm, g.antenna_gain_dbi
    FROM ts.survey_training s
    JOIN geo.gateways g ON g.id = s.serving_gateway_id
    WHERE ST_Y(s.location::geometry) BETWEEN 15.8 AND 16.3
      AND ST_X(s.location::geometry) BETWEEN 107.9 AND 108.5
      AND s.serving_gateway_id IS NOT NULL
),
predicted AS (
    SELECT
        CASE
            WHEN d_km < 0.5  THEN '0_under_500m'
            WHEN d_km < 2.0  THEN '1_500m_2km'
            WHEN d_km < 5.0  THEN '2_2_5km'
            WHEN d_km < 10.0 THEN '3_5_10km'
            WHEN d_km < 30.0 THEN '4_10_30km'
            ELSE                  '5_over_30km'
        END AS bucket,
        tx_power_dbm + antenna_gain_dbi - (
            32.45 + 20.0*log(GREATEST(d_km, 0.001)::numeric)/log(10::numeric)
                  + 20.0*log(923.0::numeric)/log(10::numeric)
            + CASE WHEN d_km > 0.1
                THEN 10.0 * (:n_value - 2.0) * log(d_km::numeric/0.1)/log(10::numeric)
                ELSE 0.0 END
        )::double precision AS rssi_pred,
        rssi_meas
    FROM joined
)
SELECT
    bucket,
    COUNT(*) AS n,
    round(SQRT(AVG((rssi_pred - rssi_meas)^2))::numeric, 2) AS rmse_db,
    round(AVG(rssi_pred - rssi_meas)::numeric, 2)           AS bias_db
FROM predicted
GROUP BY bucket
ORDER BY bucket;
