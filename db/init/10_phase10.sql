-- ============================================================================
-- 10_phase10.sql — Phase 10 (v3.1 step 1.5.x): Path loss calibration storage
--
-- Mục đích lưu DB:
--   - Audit + history (rulebackuprecovery): mỗi lần fit lưu 1 row mới
--   - Active version per environment_type: dùng cột `is_active` + soft-delete
--   - Persona 2 thẩm định: lưu metrics R², RMSE, n_samples, intercept...
--
-- Range n_path_loss_exponent: [1.6, 6.0]
--   ITU-R P.1411-12 (2023) + Rappaport Ch.4:
--     - Free space (lý thuyết): n=2.0
--     - Indoor LOS:              n=1.6-1.8
--     - Urban LOS:               n=2.7-3.5
--     - Urban NLOS:              n=3.0-5.0
--     - Indoor multifloor:       n=4.0-6.0
--   → safe production range: [1.6, 6.0]
--
-- Tuân thủ rulefordesigndatabase + rulemonitoringlogging + rulebackuprecovery.
-- Idempotent: chạy lại an toàn.
-- ============================================================================


CREATE TABLE IF NOT EXISTS path_loss_calibrations (
    id                       UUID                NOT NULL DEFAULT uuid_generate_v4(),

    environment_type         VARCHAR(50)         NOT NULL,

    -- Fitted params (Log-Distance: PL(d) = intercept + 10·n·log10(d/d0=1m))
    n_path_loss_exponent     NUMERIC(5, 3)       NOT NULL,
    intercept_db             NUMERIC(7, 3)       NOT NULL,
    sigma_db                 NUMERIC(5, 2)       NOT NULL,

    -- Goodness of fit
    r_squared                NUMERIC(6, 5)       NOT NULL,
    rmse_db                  NUMERIC(5, 2)       NOT NULL,
    mae_db                   NUMERIC(5, 2)       NOT NULL,

    -- Sample meta
    n_samples_total          INTEGER             NOT NULL,
    n_samples_fitted         INTEGER             NOT NULL,
    n_outliers_removed       INTEGER             NOT NULL DEFAULT 0,
    distance_min_m           NUMERIC(10, 2),
    distance_max_m           NUMERIC(10, 2),

    -- Filter snapshot (recovery rule)
    measurement_filters      JSONB               NOT NULL,

    -- Active version flag — chỉ 1 row 'active' per environment_type
    is_active                BOOLEAN             NOT NULL DEFAULT FALSE,

    -- Audit (rulemonitoringlogging)
    correlation_id           VARCHAR(64),
    notes                    TEXT,

    created_at               TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    deleted_at               TIMESTAMPTZ,

    CONSTRAINT pk_path_loss_calibrations PRIMARY KEY (id),

    CONSTRAINT ck_path_loss_calibrations_env
        CHECK (environment_type IN
            ('urban', 'suburban', 'rural', 'forest', 'coastal', 'mountain')),

    -- Range theo physics RF (ITU-R P.1411 / Rappaport)
    CONSTRAINT ck_path_loss_calibrations_n
        CHECK (n_path_loss_exponent >= 1.6 AND n_path_loss_exponent <= 6.0),

    CONSTRAINT ck_path_loss_calibrations_sigma
        CHECK (sigma_db >= 0 AND sigma_db <= 30),
    CONSTRAINT ck_path_loss_calibrations_r2
        CHECK (r_squared >= 0 AND r_squared <= 1),
    CONSTRAINT ck_path_loss_calibrations_rmse
        CHECK (rmse_db >= 0),
    CONSTRAINT ck_path_loss_calibrations_n_samples
        CHECK (n_samples_fitted >= 30
               AND n_samples_total >= n_samples_fitted
               AND n_outliers_removed >= 0)
);


-- Indices
CREATE INDEX IF NOT EXISTS idx_path_loss_calibrations_env_active
    ON path_loss_calibrations(environment_type)
    WHERE is_active = TRUE AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_path_loss_calibrations_env_created
    ON path_loss_calibrations(environment_type, created_at DESC)
    WHERE deleted_at IS NULL;

-- Partial unique: chỉ 1 active calibration per environment_type
CREATE UNIQUE INDEX IF NOT EXISTS uq_path_loss_calibrations_env_active
    ON path_loss_calibrations(environment_type)
    WHERE is_active = TRUE AND deleted_at IS NULL;

-- Trigger updated_at — fn_set_updated_at đã có ở 04_triggers.sql
DROP TRIGGER IF EXISTS trg_path_loss_calibrations_set_updated_at ON path_loss_calibrations;
CREATE TRIGGER trg_path_loss_calibrations_set_updated_at
    BEFORE UPDATE ON path_loss_calibrations
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


-- ============================================================================
-- SEED — Literature-derived calibrations cho 6 environment.
--
-- Mục đích: simulator/sandbox có ngay 1 active calibration per environment_type
-- để chạy được (k cần phải có drive-test trước). Khi nào có drive-test thực,
-- POST /calibrations/run sẽ deactivate row 'literature' và activate row mới.
--
-- Nguồn:
--   - ITU-R P.1411-12 (2023) §3.1: path loss exponent điển hình theo môi trường.
--   - Rappaport "Wireless Communications" (2002) Ch.4 Table 4.2.
--   - LoRa field measurements VN (Petajajarvi 2017, Sanchez 2020) cho σ.
--
-- LƯU Ý: r_squared / rmse / mae là literature-typical, KHÔNG phải fit thật từ
-- DB — service đọc cờ correlation_id='seed-literature-p1411' để biết nên
-- khuyến nghị calibrate lại với drive-test thực.
--
-- Idempotent: ON CONFLICT skip nếu đã seed (chạy lại docker compose up).
-- ============================================================================

INSERT INTO path_loss_calibrations
    (id, environment_type,
     n_path_loss_exponent, intercept_db, sigma_db,
     r_squared, rmse_db, mae_db,
     n_samples_total, n_samples_fitted, n_outliers_removed,
     distance_min_m, distance_max_m,
     measurement_filters, is_active,
     correlation_id, notes)
VALUES
    -- Urban: dense buildings, NLOS dominant (Hata Eq.1 calibrated → n≈3.5)
    ('11000000-0000-0000-0000-000000000001', 'urban',
     3.500, 40.000, 8.00,
     0.78000, 8.00, 6.00,
     100, 100, 0,
     100.00, 5000.00,
     '{"source":"literature_seed_itu_r_p1411","model":"log-distance","frequency_mhz":923,"note":"Replace via real calibration before production use"}'::jsonb,
     TRUE,
     'seed-literature-p1411',
     'Literature seed (ITU-R P.1411-12). Đô thị mật độ cao — buildings dense.'),

    -- Suburban: mid-density residential
    ('11000000-0000-0000-0000-000000000002', 'suburban',
     3.000, 38.000, 7.00,
     0.82000, 7.00, 5.50,
     100, 100, 0,
     100.00, 5000.00,
     '{"source":"literature_seed_itu_r_p1411","model":"log-distance","frequency_mhz":923,"note":"Replace via real calibration before production use"}'::jsonb,
     TRUE,
     'seed-literature-p1411',
     'Literature seed (Rappaport Table 4.2). Khu dân cư mật độ trung bình.'),

    -- Rural: open fields, low buildings
    ('11000000-0000-0000-0000-000000000003', 'rural',
     2.500, 35.000, 6.00,
     0.85000, 6.00, 4.50,
     100, 100, 0,
     100.00, 5000.00,
     '{"source":"literature_seed_itu_r_p1411","model":"log-distance","frequency_mhz":923,"note":"Replace via real calibration before production use"}'::jsonb,
     TRUE,
     'seed-literature-p1411',
     'Literature seed (Hata rural-open). Đồng bằng, đồng ruộng — Đồng bằng sông Cửu Long.'),

    -- Forest: vegetation excess loss + multipath dày
    ('11000000-0000-0000-0000-000000000004', 'forest',
     3.800, 42.000, 8.00,
     0.74000, 8.00, 6.50,
     100, 100, 0,
     100.00, 5000.00,
     '{"source":"literature_seed_itu_r_p1411","model":"log-distance","frequency_mhz":923,"note":"Replace via real calibration before production use"}'::jsonb,
     TRUE,
     'seed-literature-p1411',
     'Literature seed (ITU-R P.833 vegetation). Tán cây dày Tây Nguyên / rừng Trường Sơn.'),

    -- Coastal: flat terrain, occasional ducting (small variance)
    ('11000000-0000-0000-0000-000000000005', 'coastal',
     2.700, 36.000, 6.00,
     0.83000, 6.00, 4.50,
     100, 100, 0,
     100.00, 5000.00,
     '{"source":"literature_seed_itu_r_p1411","model":"log-distance","frequency_mhz":923,"note":"Replace via real calibration before production use"}'::jsonb,
     TRUE,
     'seed-literature-p1411',
     'Literature seed. Ven biển — Đà Nẵng, Nha Trang. Mặt nước phản xạ ổn định.'),

    -- Mountain: terrain shadowing, large variance
    ('11000000-0000-0000-0000-000000000006', 'mountain',
     3.200, 39.000, 8.50,
     0.71000, 8.50, 7.00,
     100, 100, 0,
     100.00, 5000.00,
     '{"source":"literature_seed_itu_r_p1411","model":"log-distance","frequency_mhz":923,"note":"Replace via real calibration before production use"}'::jsonb,
     TRUE,
     'seed-literature-p1411',
     'Literature seed (Longley-Rice analog). Miền núi Bắc Bộ / Tây Nguyên — terrain shadowing mạnh.')
ON CONFLICT (id) DO NOTHING;