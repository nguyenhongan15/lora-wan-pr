-- ============================================================================
-- 08_phase8.sql — Phase 8 (v3.1 step 3): Gateway candidates (H3 hex grid)
--
-- Tuân thủ rulefordesigndatabase.pdf:
--   pk_/fk_/uq_/ck_/idx_ naming, NOT NULL, TIMESTAMPTZ, GIST cho geometry,
--   FK CASCADE khi parent AOI bị xóa.
--
-- Idempotent: chạy lại an toàn.
-- ============================================================================


-- ──────────────────────────────────────────────────────────────────────────
-- gateway_candidates — vị trí ứng viên đặt gateway
--
-- Source 'grid': sinh từ H3 polyfill toàn AOI (cost = 1.0 default)
-- Source 'infra': từ OSM tower/mast/rooftop (sẽ thêm ở Phase 9 step 4, cost ~0.3)
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gateway_candidates (
    id            UUID                   NOT NULL DEFAULT uuid_generate_v4(),
    aoi_id        UUID                   NOT NULL,
    h3_index      VARCHAR(16)            NOT NULL,    -- H3 v4 cell index (15 hex chars)
    h3_resolution SMALLINT               NOT NULL,    -- 0-15
    location      GEOMETRY(POINT, 4326)  NOT NULL,    -- center của hex cell
    cost          NUMERIC(8, 3)          NOT NULL DEFAULT 1.000,  -- relative cost cho optimizer
    source        VARCHAR(20)            NOT NULL DEFAULT 'grid',
    properties    JSONB                  NOT NULL DEFAULT '{}'::jsonb,

    created_at    TIMESTAMPTZ            NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_gateway_candidates              PRIMARY KEY (id),
    CONSTRAINT uq_gateway_candidates_aoi_h3       UNIQUE (aoi_id, h3_index),
    CONSTRAINT fk_gateway_candidates_aoi_polygons FOREIGN KEY (aoi_id)
        REFERENCES aoi_polygons(id) ON DELETE CASCADE,
    CONSTRAINT ck_gateway_candidates_h3_resolution
        CHECK (h3_resolution BETWEEN 0 AND 15),
    CONSTRAINT ck_gateway_candidates_source
        CHECK (source IN ('grid', 'infra')),
    CONSTRAINT ck_gateway_candidates_cost
        CHECK (cost >= 0)
);

CREATE INDEX IF NOT EXISTS idx_gateway_candidates_aoi_id
    ON gateway_candidates(aoi_id);

CREATE INDEX IF NOT EXISTS idx_gateway_candidates_location
    ON gateway_candidates USING GIST(location);

CREATE INDEX IF NOT EXISTS idx_gateway_candidates_source
    ON gateway_candidates(source);