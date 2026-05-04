-- ============================================================================
-- _phase3_apply.sql — Idempotent surgical apply cho DB live (giữ data hiện có).
-- Chỉ thêm: gateway_specs/device_specs tables + 8 spec rows + 6 calibration rows.
-- KHÔNG đụng tới gateways/measurements/campaigns đã có trong DB.
-- ============================================================================

-- gateway_specs table
CREATE TABLE IF NOT EXISTS gateway_specs (
    id                       UUID         NOT NULL DEFAULT uuid_generate_v4(),
    vendor                   VARCHAR(100) NOT NULL,
    model                    VARCHAR(100) NOT NULL,
    frequency_band           VARCHAR(20)  NOT NULL,
    frequency_mhz            NUMERIC(7,2) NOT NULL,
    tx_power_dbm_max         NUMERIC(5,2) NOT NULL,
    antenna_gain_dbi_default NUMERIC(5,2) NOT NULL,
    sensitivity_sf7_dbm      NUMERIC(6,2),
    sensitivity_sf12_dbm     NUMERIC(6,2),
    n_concurrent_channels    SMALLINT,
    notes                    TEXT,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at               TIMESTAMPTZ,
    CONSTRAINT pk_gateway_specs              PRIMARY KEY (id),
    CONSTRAINT uq_gateway_specs_vendor_model UNIQUE (vendor, model),
    CONSTRAINT ck_gateway_specs_freq_band
        CHECK (frequency_band IN ('AS923','EU868','US915','IN865','AU915','KR920')),
    CONSTRAINT ck_gateway_specs_tx_power
        CHECK (tx_power_dbm_max >= 0 AND tx_power_dbm_max <= 30),
    CONSTRAINT ck_gateway_specs_gain
        CHECK (antenna_gain_dbi_default >= 0 AND antenna_gain_dbi_default <= 20)
);

-- device_specs table
CREATE TABLE IF NOT EXISTS device_specs (
    id                   UUID         NOT NULL DEFAULT uuid_generate_v4(),
    vendor               VARCHAR(100) NOT NULL,
    model                VARCHAR(100) NOT NULL,
    tx_power_dbm_max     NUMERIC(5,2) NOT NULL,
    antenna_gain_dbi     NUMERIC(5,2) NOT NULL,
    battery_capacity_mah INTEGER,
    notes                TEXT,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at           TIMESTAMPTZ,
    CONSTRAINT pk_device_specs              PRIMARY KEY (id),
    CONSTRAINT uq_device_specs_vendor_model UNIQUE (vendor, model),
    CONSTRAINT ck_device_specs_tx_power
        CHECK (tx_power_dbm_max >= 0 AND tx_power_dbm_max <= 20),
    CONSTRAINT ck_device_specs_gain
        CHECK (antenna_gain_dbi >= 0 AND antenna_gain_dbi <= 10)
);

-- gateways.gateway_spec_id
ALTER TABLE gateways ADD COLUMN IF NOT EXISTS gateway_spec_id UUID;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_gateways_gateway_spec') THEN
    ALTER TABLE gateways ADD CONSTRAINT fk_gateways_gateway_spec
      FOREIGN KEY (gateway_spec_id) REFERENCES gateway_specs(id) ON DELETE SET NULL;
  END IF;
END $$;

-- devices.device_spec_id
ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_spec_id UUID;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_devices_device_spec') THEN
    ALTER TABLE devices ADD CONSTRAINT fk_devices_device_spec
      FOREIGN KEY (device_spec_id) REFERENCES device_specs(id) ON DELETE SET NULL;
  END IF;
END $$;

-- gateway_specs seed (5 rows)
INSERT INTO gateway_specs (id, vendor, model, frequency_band, frequency_mhz,
                           tx_power_dbm_max, antenna_gain_dbi_default,
                           sensitivity_sf7_dbm, sensitivity_sf12_dbm,
                           n_concurrent_channels, notes)
VALUES
    ('e1000000-0000-0000-0000-000000000001','Semtech','SX1302-Reference-AS923',
     'AS923',923.00,27.00,3.00,-125.00,-137.00,8,
     'Reference design Semtech SX1302 (AS923 channel plan VN). Sensitivity per Semtech AN1200.22.'),
    ('e1000000-0000-0000-0000-000000000002','RAK Wireless','RAK7240',
     'AS923',923.00,27.00,5.00,-125.00,-137.00,8,
     'Outdoor IP65, integrated GPS. Datasheet RAK7240 v1.4 (2023).'),
    ('e1000000-0000-0000-0000-000000000003','MikroTik','wAP-LR9',
     'AS923',923.00,24.00,6.50,-123.00,-135.00,8,
     'Built-in 6.5dBi antenna, AS923 SKU. Datasheet MikroTik wAP LR9 (2024).'),
    ('e1000000-0000-0000-0000-000000000004','Dragino','LPS8N',
     'AS923',923.00,23.00,3.00,-123.00,-135.00,8,
     'Indoor low-cost (SX1308). Datasheet LPS8N v1.4.5 (2023).'),
    ('e1000000-0000-0000-0000-000000000005','Kerlink','iFemtoCell-evolution',
     'AS923',923.00,27.00,2.00,-125.00,-137.00,8,
     'Indoor enterprise, internal antenna. Datasheet iFemtoCell-evolution rev2.')
ON CONFLICT (id) DO NOTHING;

-- device_specs seed (3 rows)
INSERT INTO device_specs (id, vendor, model, tx_power_dbm_max,
                          antenna_gain_dbi, battery_capacity_mah, notes)
VALUES
    ('f1000000-0000-0000-0000-000000000001','Dragino','LHT65',
     14.00,2.15,2400,'Temp+humidity tracker, AS923. Datasheet LHT65 v1.8.'),
    ('f1000000-0000-0000-0000-000000000002','RAK Wireless','RAK7200',
     16.00,2.00,1100,'Vehicle GPS tracker, AS923. Datasheet RAK7200 v1.4.'),
    ('f1000000-0000-0000-0000-000000000003','Dragino','LSE01',
     14.00,2.00,8500,'Soil moisture (3 in 1), AS923. Datasheet LSE01 v1.6.')
ON CONFLICT (id) DO NOTHING;

-- path_loss_calibrations seed (6 rows — literature ITU-R P.1411 + Rappaport)
INSERT INTO path_loss_calibrations
    (id, environment_type, n_path_loss_exponent, intercept_db, sigma_db,
     r_squared, rmse_db, mae_db,
     n_samples_total, n_samples_fitted, n_outliers_removed,
     distance_min_m, distance_max_m,
     measurement_filters, is_active, correlation_id, notes)
VALUES
    ('11000000-0000-0000-0000-000000000001','urban',3.500,40.000,8.00,
     0.78000,8.00,6.00,100,100,0,100.00,5000.00,
     '{"source":"literature_seed_itu_r_p1411","model":"log-distance","frequency_mhz":923}'::jsonb,
     TRUE,'seed-literature-p1411','Đô thị mật độ cao.'),
    ('11000000-0000-0000-0000-000000000002','suburban',3.000,38.000,7.00,
     0.82000,7.00,5.50,100,100,0,100.00,5000.00,
     '{"source":"literature_seed_itu_r_p1411","model":"log-distance","frequency_mhz":923}'::jsonb,
     TRUE,'seed-literature-p1411','Khu dân cư mật độ trung bình.'),
    ('11000000-0000-0000-0000-000000000003','rural',2.500,35.000,6.00,
     0.85000,6.00,4.50,100,100,0,100.00,5000.00,
     '{"source":"literature_seed_itu_r_p1411","model":"log-distance","frequency_mhz":923}'::jsonb,
     TRUE,'seed-literature-p1411','Đồng bằng — Mekong Delta.'),
    ('11000000-0000-0000-0000-000000000004','forest',3.800,42.000,8.00,
     0.74000,8.00,6.50,100,100,0,100.00,5000.00,
     '{"source":"literature_seed_itu_r_p1411","model":"log-distance","frequency_mhz":923}'::jsonb,
     TRUE,'seed-literature-p1411','Tán cây dày — Tây Nguyên.'),
    ('11000000-0000-0000-0000-000000000005','coastal',2.700,36.000,6.00,
     0.83000,6.00,4.50,100,100,0,100.00,5000.00,
     '{"source":"literature_seed_itu_r_p1411","model":"log-distance","frequency_mhz":923}'::jsonb,
     TRUE,'seed-literature-p1411','Ven biển — Đà Nẵng / Nha Trang.'),
    ('11000000-0000-0000-0000-000000000006','mountain',3.200,39.000,8.50,
     0.71000,8.50,7.00,100,100,0,100.00,5000.00,
     '{"source":"literature_seed_itu_r_p1411","model":"log-distance","frequency_mhz":923}'::jsonb,
     TRUE,'seed-literature-p1411','Miền núi Bắc Bộ / Tây Nguyên.')
ON CONFLICT (id) DO NOTHING;

-- Summary
SELECT 'gateway_specs' AS t, count(*) FROM gateway_specs
UNION ALL SELECT 'device_specs', count(*) FROM device_specs
UNION ALL SELECT 'path_loss_calibrations', count(*) FROM path_loss_calibrations;
