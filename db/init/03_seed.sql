-- ============================================================================
-- 03_seed.sql — Dữ liệu mẫu cho dev/demo (Đà Nẵng AOI).
--
-- Phase v3.2 step 1: thêm 2 bảng "library":
--   - gateway_specs: catalog model gateway phổ biến (Semtech SX1302 ref,
--                    RAK7240, MikroTik wAP LR9, Dragino LPS8N, Kerlink iFemto)
--   - device_specs:  catalog end-device (Dragino LHT65, RAK7200, LSE01)
--
-- Tại sao có bảng library:
--   1. Frontend dropdown "Chọn model" thay vì user gõ tự do tx_power, gain,
--      antenna_height — giảm sai lệch input.
--   2. Khi gateways.tx_power_dbm IS NULL, simulator có thể fallback sang
--      gateway_specs.tx_power_dbm_max (xem core/validation.py — pattern
--      require_field).
--   3. Audit thẩm định P2: vendor + model rõ ràng, không "magic number".
--
-- Tuân thủ rulefordesigndatabase.pdf:
--   - Plural table names, pk_/fk_/uq_/ck_ prefix, audit trails.
--   - JSONB cho measurement_filters; CHECK enum thay ENUM type.
--   - Soft-delete: deleted_at IS NULL.
--
-- File này KHÔNG idempotent (PK conflict khi re-run) — design choice cũ;
-- giữ pattern. CREATE TABLE / ALTER TABLE đều IF NOT EXISTS để tolerate
-- partial init.
-- ============================================================================


-- ─────────────────────────────────────────────────────────────────────────────
-- Bảng: gateway_specs  (library các model gateway LoRaWAN)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gateway_specs (
    id                       UUID         NOT NULL DEFAULT uuid_generate_v4(),
    vendor                   VARCHAR(100) NOT NULL,
    model                    VARCHAR(100) NOT NULL,
    frequency_band           VARCHAR(20)  NOT NULL,
    frequency_mhz            NUMERIC(7,2) NOT NULL,
    tx_power_dbm_max         NUMERIC(5,2) NOT NULL,
    antenna_gain_dbi_default NUMERIC(5,2) NOT NULL,
    sensitivity_sf7_dbm      NUMERIC(6,2),         -- nullable: optional per datasheet
    sensitivity_sf12_dbm     NUMERIC(6,2),
    n_concurrent_channels    SMALLINT,
    notes                    TEXT,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at               TIMESTAMPTZ,

    CONSTRAINT pk_gateway_specs              PRIMARY KEY (id),
    CONSTRAINT uq_gateway_specs_vendor_model UNIQUE (vendor, model),
    CONSTRAINT ck_gateway_specs_freq_band
        CHECK (frequency_band IN ('AS923', 'EU868', 'US915', 'IN865', 'AU915', 'KR920')),
    CONSTRAINT ck_gateway_specs_tx_power
        CHECK (tx_power_dbm_max >= 0 AND tx_power_dbm_max <= 30),
    CONSTRAINT ck_gateway_specs_gain
        CHECK (antenna_gain_dbi_default >= 0 AND antenna_gain_dbi_default <= 20)
);


-- ─────────────────────────────────────────────────────────────────────────────
-- Bảng: device_specs  (library các end-device LoRaWAN)
-- ─────────────────────────────────────────────────────────────────────────────
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
        CHECK (tx_power_dbm_max >= 0 AND tx_power_dbm_max <= 30),
    CONSTRAINT ck_device_specs_gain
        CHECK (antenna_gain_dbi >= 0 AND antenna_gain_dbi <= 10)
);


-- ─────────────────────────────────────────────────────────────────────────────
-- ALTER existing tables — wire FK từ gateways/devices về library.
-- Cột nullable: gateway/device chưa biết model vẫn lưu được, services raise
-- MissingFieldError lúc cần (xem core/validation.py).
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE gateways ADD COLUMN IF NOT EXISTS gateway_spec_id UUID;
ALTER TABLE gateways DROP CONSTRAINT IF EXISTS fk_gateways_gateway_specs;
ALTER TABLE gateways
    ADD CONSTRAINT fk_gateways_gateway_specs
        FOREIGN KEY (gateway_spec_id) REFERENCES gateway_specs(id);

ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_spec_id UUID;
ALTER TABLE devices DROP CONSTRAINT IF EXISTS fk_devices_device_specs;
ALTER TABLE devices
    ADD CONSTRAINT fk_devices_device_specs
        FOREIGN KEY (device_spec_id) REFERENCES device_specs(id);


-- ============================================================================
-- SEED DATA — Đà Nẵng pilot
-- ============================================================================

-- Project
INSERT INTO projects (id, name, description, organization)
VALUES (
    'a0000000-0000-0000-0000-000000000001',
    'LoRa Da Nang Pilot',
    'Khảo sát phủ sóng LoRaWAN tại Đà Nẵng',
    'VGU Research Lab'
);


-- ─────────────────────────────────────────────────────────────────────────────
-- Gateway specs library (5 model phổ biến tại VN — band AS923 chính)
-- Nguồn: datasheet vendor + LoRa Alliance recommended sensitivity table.
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO gateway_specs (id, vendor, model, frequency_band, frequency_mhz,
                           tx_power_dbm_max, antenna_gain_dbi_default,
                           sensitivity_sf7_dbm, sensitivity_sf12_dbm,
                           n_concurrent_channels, notes)
VALUES
    -- Semtech SX1302 reference design — baseline cho mọi ODM/OEM dùng SX1302
    ('e1000000-0000-0000-0000-000000000001',
     'Semtech',          'SX1302-Reference-AS923',
     'AS923', 923.00,
     27.00,  3.00,
     -125.00, -137.00,
     8,
     'Reference design Semtech SX1302 (AS923 channel plan VN). Sensitivity per Semtech AN1200.22.'),

    -- RAK7240 outdoor enterprise — phổ biến trong các pilot smart-city VN
    ('e1000000-0000-0000-0000-000000000002',
     'RAK Wireless',     'RAK7240',
     'AS923', 923.00,
     27.00,  5.00,
     -125.00, -137.00,
     8,
     'Outdoor IP65, integrated GPS. Datasheet RAK7240 v1.4 (2023).'),

    -- MikroTik wAP LR9 — kit indoor giá rẻ, antenna built-in
    ('e1000000-0000-0000-0000-000000000003',
     'MikroTik',         'wAP-LR9',
     'AS923', 923.00,
     24.00,  6.50,
     -123.00, -135.00,
     8,
     'Built-in 6.5dBi antenna, AS923 SKU. Datasheet MikroTik wAP LR9 (2024).'),

    -- Dragino LPS8N — gateway indoor LoRaWAN entry-level
    ('e1000000-0000-0000-0000-000000000004',
     'Dragino',          'LPS8N',
     'AS923', 923.00,
     23.00,  3.00,
     -123.00, -135.00,
     8,
     'Indoor low-cost (SX1308). Datasheet LPS8N v1.4.5 (2023).'),

    -- Kerlink iFemtoCell — enterprise indoor, dùng nhiều ở Telco VN
    ('e1000000-0000-0000-0000-000000000005',
     'Kerlink',          'iFemtoCell-evolution',
     'AS923', 923.00,
     27.00,  2.00,
     -125.00, -137.00,
     8,
     'Indoor enterprise, internal antenna. Datasheet iFemtoCell-evolution rev2.');


-- ─────────────────────────────────────────────────────────────────────────────
-- Device specs library (3 device LoRa AS923 phổ biến)
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO device_specs (id, vendor, model, tx_power_dbm_max,
                          antenna_gain_dbi, battery_capacity_mah, notes)
VALUES
    ('f1000000-0000-0000-0000-000000000001',
     'Dragino', 'LHT65',
     14.00, 2.15, 2400,
     'Temp+humidity tracker, AS923. Datasheet LHT65 v1.8.'),

    ('f1000000-0000-0000-0000-000000000002',
     'RAK Wireless', 'RAK7200',
     16.00, 2.00, 1100,
     'Vehicle GPS tracker, AS923. Datasheet RAK7200 v1.4.'),

    ('f1000000-0000-0000-0000-000000000003',
     'Dragino', 'LSE01',
     14.00, 2.00, 8500,
     'Soil moisture (3 in 1), AS923. Datasheet LSE01 v1.6.');


-- ─────────────────────────────────────────────────────────────────────────────
-- Gateways (2 tại Đà Nẵng) — wire vào gateway_specs library
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO gateways
    (id, project_id, gateway_eui, name, location,
     altitude_m, antenna_height_m, tx_power_dbm, antenna_type,
     gateway_spec_id, installed_at)
VALUES
    -- GW-Central: dùng SX1302 reference baseline, antenna fiberglass omni
    ('b0000000-0000-0000-0000-000000000001',
     'a0000000-0000-0000-0000-000000000001',
     'aa01bb02cc03dd04',
     'GW-DaNang-Central',
     ST_SetSRID(ST_MakePoint(108.2022, 16.0544), 4326),
     10, 6, 27, 'omni-fiberglass-3dBi',
     'e1000000-0000-0000-0000-000000000001',
     NOW() - INTERVAL '30 days'),

    -- GW-West: RAK7240 outdoor, antenna 5dBi mặc định
    ('b0000000-0000-0000-0000-000000000002',
     'a0000000-0000-0000-0000-000000000001',
     'aa05bb06cc07dd08',
     'GW-DaNang-West',
     ST_SetSRID(ST_MakePoint(108.1580, 16.0600), 4326),
     15, 8, 27, 'omni-fiberglass-5dBi',
     'e1000000-0000-0000-0000-000000000002',
     NOW() - INTERVAL '25 days');


-- ─────────────────────────────────────────────────────────────────────────────
-- Device — LHT65 tracker
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO devices (id, project_id, dev_eui, name, device_type, device_spec_id)
VALUES (
    'c0000000-0000-0000-0000-000000000001',
    'a0000000-0000-0000-0000-000000000001',
    '70b3d57ed0012345',
    'Node-01',
    'tracker',
    'f1000000-0000-0000-0000-000000000001'
);


-- ─────────────────────────────────────────────────────────────────────────────
-- Campaign + 100 measurements (random ±2.5km quanh GW-Central)
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO campaigns
    (id, project_id, name, environment_type,
     start_date, end_date, weather_condition)
VALUES (
    'd0000000-0000-0000-0000-000000000001',
    'a0000000-0000-0000-0000-000000000001',
    'Drive Test Q1-2025',
    'urban',
    '2025-01-15',
    '2025-01-30',
    'clear'
);

INSERT INTO measurements (
    gateway_id, campaign_id, device_id,
    location, altitude_m,
    rssi_dbm, snr_db,
    spreading_factor, bandwidth_khz, coding_rate,
    tx_power_dbm, frame_count, measured_at, data_source
)
SELECT
    CASE WHEN i % 2 = 0
         THEN 'b0000000-0000-0000-0000-000000000001'::uuid
         ELSE 'b0000000-0000-0000-0000-000000000002'::uuid
    END,
    'd0000000-0000-0000-0000-000000000001',
    'c0000000-0000-0000-0000-000000000001',
    ST_SetSRID(
        ST_MakePoint(
            108.2022 + (random() - 0.5) * 0.05,
            16.0544  + (random() - 0.5) * 0.05
        ), 4326
    ),
    5 + random() * 20,
    -60 - random() * 60,
    -5  + random() * 15,
    (ARRAY[7,8,9,10,11,12])[1 + (i % 6)],
    125,
    5,
    14,
    i,
    NOW() - (random() * INTERVAL '15 days'),
    'seed'
FROM generate_series(1, 100) AS i;
