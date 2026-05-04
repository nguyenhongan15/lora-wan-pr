-- ============================================================================
-- 04_triggers.sql — Auto-update `updated_at` khi có UPDATE
--
-- Tuân thủ rulefordesigndatabase.pdf Mục 5:
--   "updated_at (ngày cập nhật cuối, TỰ ĐỘNG TRIGGER khi có UPDATE)"
--
-- PostgreSQL khác MySQL: không có ON UPDATE CURRENT_TIMESTAMP.
-- Phải dùng TRIGGER để simulate.
--
-- Tuân thủ Mục 3 (Normalization):
--   - Trigger thay vì lưu cột tính được
--   - 1 function dùng chung cho mọi bảng (DRY principle)
-- ============================================================================


-- ──────────────────────────────────────────────────────────────────────────
-- 1. Function dùng chung: set NEW.updated_at = NOW()
-- ──────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION fn_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    -- Chỉ update nếu giá trị thực sự thay đổi (optimization)
    IF NEW IS DISTINCT FROM OLD THEN
        NEW.updated_at := NOW();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ──────────────────────────────────────────────────────────────────────────
-- 2. Gắn trigger vào từng bảng có cột `updated_at`
-- ──────────────────────────────────────────────────────────────────────────

CREATE TRIGGER trg_projects_set_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_gateways_set_updated_at
    BEFORE UPDATE ON gateways
    FOR EACH ROW
    EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_devices_set_updated_at
    BEFORE UPDATE ON devices
    FOR EACH ROW
    EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_campaigns_set_updated_at
    BEFORE UPDATE ON campaigns
    FOR EACH ROW
    EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_environment_zones_set_updated_at
    BEFORE UPDATE ON environment_zones
    FOR EACH ROW
    EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_measurements_set_updated_at
    BEFORE UPDATE ON measurements
    FOR EACH ROW
    EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_ml_models_set_updated_at
    BEFORE UPDATE ON ml_models
    FOR EACH ROW
    EXECUTE FUNCTION fn_set_updated_at();


-- ============================================================================
-- HELPER VIEWS — "active records" (đã loại soft-deleted)
-- ============================================================================
-- App có thể SELECT trực tiếp view, không cần nhớ WHERE deleted_at IS NULL

CREATE OR REPLACE VIEW v_active_projects AS
    SELECT * FROM projects     WHERE deleted_at IS NULL;

CREATE OR REPLACE VIEW v_active_gateways AS
    SELECT * FROM gateways     WHERE deleted_at IS NULL;

CREATE OR REPLACE VIEW v_active_devices AS
    SELECT * FROM devices      WHERE deleted_at IS NULL;

CREATE OR REPLACE VIEW v_active_campaigns AS
    SELECT * FROM campaigns    WHERE deleted_at IS NULL;

CREATE OR REPLACE VIEW v_active_measurements AS
    SELECT * FROM measurements WHERE deleted_at IS NULL;

CREATE OR REPLACE VIEW v_active_ml_models AS
    SELECT * FROM ml_models    WHERE deleted_at IS NULL;
