-- scripts/cleanup_seed.sql
-- Dọn toàn bộ seed data cũ để chuẩn bị import data thật từ lpwanmapper.
--
-- ⚠️  CẢNH BÁO: Xoá HẾT data nghiệp vụ.
--               Không ảnh hưởng schema (tables, triggers, views vẫn còn).
--
-- Chạy:
--   docker exec -it lora_postgres psql -U lora_user -d lora_coverage -f /scripts/cleanup_seed.sql
-- Hoặc trong pgAdmin: mở Query Tool → paste → F5

BEGIN;

-- Hard-truncate vì đây là dữ liệu test. Khi chạy production nên soft-delete.
TRUNCATE TABLE
    measurements,
    ml_predictions,
    prediction_grids,
    heatmap_caches,
    ml_models,
    campaign_zones,
    campaigns,
    devices,
    gateways,
    projects
RESTART IDENTITY CASCADE;

-- environment_zones giữ lại nếu có (master data). Bỏ comment nếu muốn xoá luôn:
-- TRUNCATE TABLE environment_zones RESTART IDENTITY CASCADE;

COMMIT;

-- Verify: tất cả bảng đều 0
SELECT 'projects'         AS tbl, COUNT(*) FROM projects
UNION ALL SELECT 'gateways',         COUNT(*) FROM gateways
UNION ALL SELECT 'devices',          COUNT(*) FROM devices
UNION ALL SELECT 'campaigns',        COUNT(*) FROM campaigns
UNION ALL SELECT 'measurements',     COUNT(*) FROM measurements
UNION ALL SELECT 'ml_models',        COUNT(*) FROM ml_models
UNION ALL SELECT 'prediction_grids', COUNT(*) FROM prediction_grids
ORDER BY tbl;
