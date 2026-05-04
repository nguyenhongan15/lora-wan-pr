-- ============================================================================
-- 01_schema.sql — Schema cho hệ thống phân tích phủ sóng LoRaWAN
--
-- Tuân thủ rulefordesigndatabase.pdf:
--   Mục 1 — Naming: snake_case, plural, không tiền tố tbl_; FK = <singular>_id
--                   Constraint: pk_<table>, fk_<table>_<ref>, uq_<table>_<col>
--   Mục 2 — Data Types: NOT NULL tối đa, TIMESTAMPTZ, enum qua CHECK, không FLOAT cho tiền
--   Mục 3 — 3NF: junction table cho M-N, không lưu cột tính được
--   Mục 5 — Audit Trails: mọi bảng nghiệp vụ có created_at + updated_at + deleted_at
--   Mục 6 — PK: UUID v4 (có thể nâng lên v7 sau nếu cần)
--
-- Tuân thủ Quy_tắc_Caching_Performance_State.pdf:
--   - heatmap_cache phải có TTL (expires_at) — "Tuyệt đối phải có TTL"
--
-- Tuân thủ LoRaWAN TS002 §7:
--   - DevEUI, GatewayEUI phải là 16 hex chars (8 bytes)
--   - Spreading Factor: 7-12
-- ============================================================================

-- ── Extensions ─────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ============================================================================
-- Bảng: projects (Mục 1: plural noun)
-- ============================================================================
CREATE TABLE projects (
    id           UUID         NOT NULL DEFAULT uuid_generate_v4(),
    name         VARCHAR(255) NOT NULL,
    description  TEXT,
    organization VARCHAR(255),
    -- Audit trails (Mục 5 bắt buộc)
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at   TIMESTAMPTZ,                           -- NULL = chưa xoá
    CONSTRAINT pk_projects PRIMARY KEY (id)
);


-- ============================================================================
-- Bảng: gateways  (LoRaWAN gateways — nơi cài đặt ăng-ten)
-- ============================================================================
CREATE TABLE gateways (
    id               UUID         NOT NULL DEFAULT uuid_generate_v4(),
    project_id       UUID         NOT NULL,
    gateway_eui      VARCHAR(16)  NOT NULL,              -- 8 bytes = 16 hex (TS002)
    name             VARCHAR(255),
    location         GEOMETRY(Point, 4326),              -- có thể NULL khi chưa có toạ độ
    altitude_m       DOUBLE PRECISION,
    antenna_height_m DOUBLE PRECISION,
    tx_power_dbm     DOUBLE PRECISION,
    antenna_type     VARCHAR(100),
    installed_at     TIMESTAMPTZ,
    -- Audit trails
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at       TIMESTAMPTZ,

    -- Constraints (Mục 1: đặt tên có prefix)
    CONSTRAINT pk_gateways            PRIMARY KEY (id),
    CONSTRAINT fk_gateways_projects   FOREIGN KEY (project_id)
                                      REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT uq_gateways_gateway_eui UNIQUE (gateway_eui),
    -- LoRaWAN TS002: EUI phải là 16 ký tự hex
    CONSTRAINT ck_gateways_gateway_eui CHECK (gateway_eui ~ '^[0-9a-f]{16}$')
);


-- ============================================================================
-- Bảng: devices  (end-device gắn cảm biến, chạy LoRa)
-- ============================================================================
CREATE TABLE devices (
    id          UUID         NOT NULL DEFAULT uuid_generate_v4(),
    project_id  UUID         NOT NULL,
    dev_eui     VARCHAR(16)  NOT NULL,
    name        VARCHAR(255),
    device_type VARCHAR(100),                            -- tracker, sensor, node...
    -- Audit trails
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ,

    CONSTRAINT pk_devices           PRIMARY KEY (id),
    CONSTRAINT fk_devices_projects  FOREIGN KEY (project_id)
                                    REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT uq_devices_dev_eui   UNIQUE (dev_eui),
    CONSTRAINT ck_devices_dev_eui   CHECK (dev_eui ~ '^[0-9a-f]{16}$')
);


-- ============================================================================
-- Bảng: campaigns  (đợt đo đạc)
-- ============================================================================
-- environment_type dùng CHECK thay vì ENUM để dễ thêm giá trị sau
CREATE TABLE campaigns (
    id                UUID         NOT NULL DEFAULT uuid_generate_v4(),
    project_id        UUID         NOT NULL,
    name              VARCHAR(255) NOT NULL,
    environment_type  VARCHAR(50),
    start_date        DATE,
    end_date          DATE,
    equipment_notes   TEXT,
    weather_condition VARCHAR(50),
    -- Audit trails
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at        TIMESTAMPTZ,

    CONSTRAINT pk_campaigns           PRIMARY KEY (id),
    CONSTRAINT fk_campaigns_projects  FOREIGN KEY (project_id)
                                      REFERENCES projects(id) ON DELETE CASCADE,
    -- Enforce tập giá trị (Mục 2: không để string tự do)
    CONSTRAINT ck_campaigns_env_type
        CHECK (environment_type IS NULL OR environment_type IN
               ('urban', 'suburban', 'rural', 'forest', 'coastal', 'mountain')),
    CONSTRAINT ck_campaigns_weather
        CHECK (weather_condition IS NULL OR weather_condition IN
               ('clear', 'cloudy', 'rainy', 'foggy', 'stormy')),
    -- Logic: end_date không được trước start_date
    CONSTRAINT ck_campaigns_date_range
        CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);


-- ============================================================================
-- Bảng: environment_zones  (vùng đặc thù — toà nhà, công viên, khu đô thị)
-- ============================================================================
CREATE TABLE environment_zones (
    id                    UUID         NOT NULL DEFAULT uuid_generate_v4(),
    boundary              GEOMETRY(Polygon, 4326) NOT NULL,
    zone_type             VARCHAR(50),
    building_density      DOUBLE PRECISION,
    avg_building_height_m DOUBLE PRECISION,
    ndvi                  DOUBLE PRECISION,
    land_use              VARCHAR(50),
    -- Audit trails (master data — không cần deleted_at)
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_environment_zones PRIMARY KEY (id),
    CONSTRAINT ck_environment_zones_building_density
        CHECK (building_density IS NULL OR
               (building_density >= 0 AND building_density <= 1)),
    CONSTRAINT ck_environment_zones_ndvi
        CHECK (ndvi IS NULL OR (ndvi >= -1 AND ndvi <= 1))
);


-- ============================================================================
-- Bảng junction: campaign_zones  (N-N — 3NF, Mục 3)
-- ============================================================================
CREATE TABLE campaign_zones (
    id          UUID         NOT NULL DEFAULT uuid_generate_v4(),
    campaign_id UUID         NOT NULL,
    zone_id     UUID         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_campaign_zones                    PRIMARY KEY (id),
    CONSTRAINT fk_campaign_zones_campaigns          FOREIGN KEY (campaign_id)
                                                    REFERENCES campaigns(id) ON DELETE CASCADE,
    CONSTRAINT fk_campaign_zones_environment_zones  FOREIGN KEY (zone_id)
                                                    REFERENCES environment_zones(id) ON DELETE CASCADE,
    CONSTRAINT uq_campaign_zones_campaign_zone      UNIQUE (campaign_id, zone_id)
);


-- ============================================================================
-- Bảng: measurements  (CORE — mỗi lần uplink LoRa → 1 record)
-- ============================================================================
CREATE TABLE measurements (
    id               UUID          NOT NULL DEFAULT uuid_generate_v4(),
    gateway_id       UUID          NOT NULL,
    campaign_id      UUID          NOT NULL,
    zone_id          UUID,                                -- optional: vùng gặp phải
    device_id        UUID,                                -- optional: webhook có thể không biết
    location         GEOMETRY(Point, 4326) NOT NULL,
    altitude_m       DOUBLE PRECISION,
    rssi_dbm         DOUBLE PRECISION NOT NULL,           -- signal strength: -30..-140
    snr_db           DOUBLE PRECISION,                    -- -20..+10
    spreading_factor SMALLINT,                            -- 7..12 (TS002)
    bandwidth_khz    SMALLINT,                            -- 125, 250, 500
    coding_rate      SMALLINT,                            -- 5..8
    tx_power_dbm     DOUBLE PRECISION,
    frame_count      INTEGER,
    measured_at      TIMESTAMPTZ   NOT NULL,
    hdop             DOUBLE PRECISION,
    data_source      VARCHAR(20)   NOT NULL DEFAULT 'manual',
    -- Audit trails
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    deleted_at       TIMESTAMPTZ,

    CONSTRAINT pk_measurements                  PRIMARY KEY (id),
    CONSTRAINT fk_measurements_gateways         FOREIGN KEY (gateway_id)
                                                REFERENCES gateways(id),
    CONSTRAINT fk_measurements_campaigns        FOREIGN KEY (campaign_id)
                                                REFERENCES campaigns(id),
    CONSTRAINT fk_measurements_environment_zones FOREIGN KEY (zone_id)
                                                REFERENCES environment_zones(id),
    CONSTRAINT fk_measurements_devices          FOREIGN KEY (device_id)
                                                REFERENCES devices(id),

    -- LoRaWAN physical constraints
    CONSTRAINT ck_measurements_rssi_range
        CHECK (rssi_dbm >= -200 AND rssi_dbm <= 20),
    CONSTRAINT ck_measurements_snr_range
        CHECK (snr_db IS NULL OR (snr_db >= -30 AND snr_db <= 30)),
    CONSTRAINT ck_measurements_sf_range
        CHECK (spreading_factor IS NULL OR
               (spreading_factor BETWEEN 7 AND 12)),
    CONSTRAINT ck_measurements_bw_allowed
        CHECK (bandwidth_khz IS NULL OR
               bandwidth_khz IN (125, 250, 500)),
    CONSTRAINT ck_measurements_cr_range
        CHECK (coding_rate IS NULL OR
               (coding_rate BETWEEN 5 AND 8)),

    -- data_source enum
    CONSTRAINT ck_measurements_data_source
        CHECK (data_source IN
               ('manual', 'csv_import', 'api', 'webhook', 'lpwanmapper', 'seed'))
);


-- ============================================================================
-- Bảng: ml_models  (metadata của model đã train)
-- ============================================================================
CREATE TABLE ml_models (
    id                 UUID          NOT NULL DEFAULT uuid_generate_v4(),
    name               VARCHAR(255)  NOT NULL,
    algorithm          VARCHAR(50)   NOT NULL,
    version            VARCHAR(50),
    rmse_db            DOUBLE PRECISION,
    mae_db             DOUBLE PRECISION,
    r2_score           DOUBLE PRECISION,
    hyperparameters    JSONB,
    feature_importance JSONB,
    mlflow_run_id      VARCHAR(255),
    trained_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    -- Audit trails (riêng của row, khác với trained_at)
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    deleted_at         TIMESTAMPTZ,

    CONSTRAINT pk_ml_models           PRIMARY KEY (id),
    CONSTRAINT ck_ml_models_algorithm
        CHECK (algorithm IN
               ('idw', 'kriging', 'xgboost', 'random_forest',
                'gaussian_process', 'okumura_hata', 'log_distance'))
);


-- ============================================================================
-- Bảng: ml_predictions  (prediction cho từng measurement cụ thể)
-- ============================================================================
-- LƯU Ý: bỏ cột residual_db GENERATED (Mục 3 — không lưu cột tính được)
-- Residual = predicted - actual sẽ được tính qua VIEW v_ml_prediction_residuals
CREATE TABLE ml_predictions (
    id                     UUID             NOT NULL DEFAULT uuid_generate_v4(),
    measurement_id         UUID             NOT NULL,
    model_id               UUID             NOT NULL,
    predicted_rssi_dbm     DOUBLE PRECISION NOT NULL,
    prediction_uncertainty DOUBLE PRECISION,
    feature_values         JSONB,
    created_at             TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_ml_predictions               PRIMARY KEY (id),
    CONSTRAINT fk_ml_predictions_measurements  FOREIGN KEY (measurement_id)
                                               REFERENCES measurements(id) ON DELETE CASCADE,
    CONSTRAINT fk_ml_predictions_ml_models     FOREIGN KEY (model_id)
                                               REFERENCES ml_models(id)
);


-- ============================================================================
-- Bảng: prediction_grids  (heatmap phủ sóng - lưới tính sẵn)
-- ============================================================================
CREATE TABLE prediction_grids (
    id                 UUID             NOT NULL DEFAULT uuid_generate_v4(),
    model_id           UUID             NOT NULL,
    campaign_id        UUID             NOT NULL,
    location           GEOMETRY(Point, 4326) NOT NULL,
    predicted_rssi_dbm DOUBLE PRECISION NOT NULL,
    uncertainty        DOUBLE PRECISION,
    grid_resolution_m  INTEGER          NOT NULL DEFAULT 50,
    created_at         TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_prediction_grids             PRIMARY KEY (id),
    CONSTRAINT fk_prediction_grids_ml_models   FOREIGN KEY (model_id)
                                               REFERENCES ml_models(id),
    CONSTRAINT fk_prediction_grids_campaigns   FOREIGN KEY (campaign_id)
                                               REFERENCES campaigns(id),
    CONSTRAINT ck_prediction_grids_resolution
        CHECK (grid_resolution_m > 0 AND grid_resolution_m <= 1000)
);


-- ============================================================================
-- Bảng: heatmap_caches  (tile cache cho Mapbox)
-- ============================================================================
-- Tuân thủ Quy_tắc_Caching_Performance_State.pdf: MUST have TTL
CREATE TABLE heatmap_caches (
    id           UUID         NOT NULL DEFAULT uuid_generate_v4(),
    campaign_id  UUID         NOT NULL,
    model_id     UUID         NOT NULL,
    zoom_level   SMALLINT     NOT NULL,
    tile_data    JSONB        NOT NULL,
    bbox         GEOMETRY(Polygon, 4326),
    generated_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ  NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),

    CONSTRAINT pk_heatmap_caches                PRIMARY KEY (id),
    CONSTRAINT fk_heatmap_caches_campaigns      FOREIGN KEY (campaign_id)
                                                REFERENCES campaigns(id) ON DELETE CASCADE,
    CONSTRAINT fk_heatmap_caches_ml_models      FOREIGN KEY (model_id)
                                                REFERENCES ml_models(id),
    CONSTRAINT uq_heatmap_caches_campaign_model_zoom
        UNIQUE (campaign_id, model_id, zoom_level),
    CONSTRAINT ck_heatmap_caches_zoom_range
        CHECK (zoom_level BETWEEN 0 AND 22),
    CONSTRAINT ck_heatmap_caches_expires_after
        CHECK (expires_at > generated_at)
);


-- ============================================================================
-- VIEW: v_ml_prediction_residuals  (tính residual on-demand, không lưu)
-- Mục 3 — thay cho cột GENERATED sai
-- ============================================================================
CREATE OR REPLACE VIEW v_ml_prediction_residuals AS
SELECT
    p.id                                  AS prediction_id,
    p.measurement_id,
    p.model_id,
    p.predicted_rssi_dbm,
    m.rssi_dbm                            AS actual_rssi_dbm,
    (p.predicted_rssi_dbm - m.rssi_dbm)   AS residual_db,
    p.prediction_uncertainty,
    p.created_at
FROM ml_predictions p
JOIN measurements   m ON m.id = p.measurement_id
WHERE m.deleted_at IS NULL;
