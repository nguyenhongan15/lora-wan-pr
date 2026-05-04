-- ============================================================================
-- alter_path_loss_calibrations_n_range.sql
-- Phase v3.1 step 1.5.x — Option C
--
-- Update CHECK constraint cho n_path_loss_exponent theo chuẩn physics RF
-- (ITU-R P.1411, Rappaport "Wireless Communications" Ch.4).
--
-- Range cũ: [1.0, 6.0] — quá rộng
-- Range mới: [1.6, 6.0] — đúng physics minimum (free space n=2.0)
--
-- Run idempotent: chạy lại an toàn (drop + re-create constraint).
-- ============================================================================

ALTER TABLE path_loss_calibrations
    DROP CONSTRAINT IF EXISTS ck_path_loss_calibrations_n;

ALTER TABLE path_loss_calibrations
    ADD CONSTRAINT ck_path_loss_calibrations_n
        CHECK (n_path_loss_exponent >= 1.6 AND n_path_loss_exponent <= 6.0);

-- Verify:
-- \d path_loss_calibrations
-- → CHECK (n_path_loss_exponent >= 1.6 AND n_path_loss_exponent <= 6.0)