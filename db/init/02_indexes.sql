-- ============================================================================
-- 02_indexes.sql — Index strategy
--
-- Tuân thủ rulefordesigndatabase.pdf Mục 4:
--   (1) LUÔN index mọi Foreign Key (SQL không tự làm)
--   (2) Index cột dùng trong WHERE, ORDER BY, GROUP BY
--   (3) Composite Index cho query nhiều cột — Left-most prefix rule
--   (4) Tránh over-index (không index cột boolean 99% cùng giá trị)
--
-- Tuân thủ Quy_tắc_Caching_Performance_State.pdf:
--   - Fix N+1: với query JOIN nhiều lần, composite index giúp planner chọn đúng
--   - Partial index cho soft-delete (luôn WHERE deleted_at IS NULL) giúp giảm size
-- ============================================================================


-- ──────────────────────────────────────────────────────────────────────────
-- 1. Spatial indexes (GIST) — bắt buộc cho geometry
-- ──────────────────────────────────────────────────────────────────────────
CREATE INDEX idx_gateways_location
    ON gateways USING GIST (location);

CREATE INDEX idx_measurements_location
    ON measurements USING GIST (location);

CREATE INDEX idx_prediction_grids_location
    ON prediction_grids USING GIST (location);

CREATE INDEX idx_environment_zones_boundary
    ON environment_zones USING GIST (boundary);

CREATE INDEX idx_heatmap_caches_bbox
    ON heatmap_caches USING GIST (bbox);


-- ──────────────────────────────────────────────────────────────────────────
-- 2. FK indexes — Mục 4(1): tăng tốc JOIN + tránh sequential scan khi cascade
-- ──────────────────────────────────────────────────────────────────────────
CREATE INDEX idx_gateways_project_id                 ON gateways(project_id);
CREATE INDEX idx_devices_project_id                  ON devices(project_id);
CREATE INDEX idx_campaigns_project_id                ON campaigns(project_id);

CREATE INDEX idx_campaign_zones_campaign_id          ON campaign_zones(campaign_id);
CREATE INDEX idx_campaign_zones_zone_id              ON campaign_zones(zone_id);

CREATE INDEX idx_measurements_gateway_id             ON measurements(gateway_id);
CREATE INDEX idx_measurements_device_id              ON measurements(device_id);
CREATE INDEX idx_measurements_zone_id                ON measurements(zone_id);

CREATE INDEX idx_ml_predictions_measurement_id       ON ml_predictions(measurement_id);
CREATE INDEX idx_ml_predictions_model_id             ON ml_predictions(model_id);

CREATE INDEX idx_prediction_grids_model_id           ON prediction_grids(model_id);

CREATE INDEX idx_heatmap_caches_campaign_id          ON heatmap_caches(campaign_id);
CREATE INDEX idx_heatmap_caches_model_id             ON heatmap_caches(model_id);


-- ──────────────────────────────────────────────────────────────────────────
-- 3. Unique-lookup indexes (dùng trong WHERE với giá trị chính xác)
-- ──────────────────────────────────────────────────────────────────────────
-- UNIQUE constraint tự sinh ra index rồi, nhưng ta khai báo lại cho rõ ràng:
-- - gateways.gateway_eui: webhook query liên tục
-- - devices.dev_eui: webhook, lpwan_sync query liên tục
-- (Postgres sẽ dedupe, không tạo thừa)


-- ──────────────────────────────────────────────────────────────────────────
-- 4. Composite indexes — query phổ biến nhất trong app
-- ──────────────────────────────────────────────────────────────────────────

-- router measurements.py: WHERE campaign_id=? ORDER BY measured_at DESC
-- → composite index phục vụ CẢ WHERE CẢ ORDER BY trong 1 lần scan
CREATE INDEX idx_measurements_campaign_id_measured_at
    ON measurements (campaign_id, measured_at DESC);

-- router webhook.py dedup check (TS002 DedupWindow):
-- WHERE device_id=? AND gateway_id=? AND frame_count=? AND measured_at > NOW() - '5 min'
CREATE INDEX idx_measurements_dedup
    ON measurements (device_id, gateway_id, frame_count, measured_at DESC);

-- router predict.py get_prediction_grid:
-- WHERE campaign_id=? [AND rssi >= ?] ORDER BY predicted_rssi_dbm DESC
CREATE INDEX idx_prediction_grids_campaign_rssi
    ON prediction_grids (campaign_id, predicted_rssi_dbm DESC);


-- ──────────────────────────────────────────────────────────────────────────
-- 5. Partial indexes cho soft delete
-- ──────────────────────────────────────────────────────────────────────────
-- App luôn query `WHERE deleted_at IS NULL` → partial index
-- nhỏ hơn (chỉ index row chưa xoá) và nhanh hơn full index
CREATE INDEX idx_gateways_active_by_project
    ON gateways (project_id) WHERE deleted_at IS NULL;

CREATE INDEX idx_devices_active_by_project
    ON devices (project_id) WHERE deleted_at IS NULL;

CREATE INDEX idx_campaigns_active_by_project
    ON campaigns (project_id) WHERE deleted_at IS NULL;

CREATE INDEX idx_measurements_active_by_campaign
    ON measurements (campaign_id, measured_at DESC)
    WHERE deleted_at IS NULL;


-- ──────────────────────────────────────────────────────────────────────────
-- 6. TTL cleanup support
-- ──────────────────────────────────────────────────────────────────────────
-- Hỗ trợ cron job dọn cache: DELETE FROM heatmap_caches WHERE expires_at < NOW()
CREATE INDEX idx_heatmap_caches_expires_at
    ON heatmap_caches (expires_at);


-- ──────────────────────────────────────────────────────────────────────────
-- 7. Algorithm lookup (query "list model by algorithm")
-- ──────────────────────────────────────────────────────────────────────────
CREATE INDEX idx_ml_models_algorithm
    ON ml_models (algorithm)
    WHERE deleted_at IS NULL;


-- ============================================================================
-- GHI CHÚ về những gì KHÔNG index (theo Mục 4 — tránh over-index):
-- ============================================================================
-- ✗ measurements.data_source: chỉ có 6 giá trị, cardinality thấp
-- ✗ measurements.spreading_factor: chỉ có 6 giá trị (7-12)
-- ✗ campaigns.environment_type: chỉ có 6 giá trị
-- ✗ Boolean/enum với phân bố lệch: tốn write, không tăng read đáng kể
-- ============================================================================
