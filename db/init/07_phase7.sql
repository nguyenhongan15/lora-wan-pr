-- ============================================================================
-- 07_phase7.sql — Phase 7 (v3.1 step 2): AOI polygons (admin boundary từ OSM)
--
-- Tuân thủ rulefordesigndatabase.pdf:
--   Mục 1: pk_/fk_/uq_/ck_/idx_ naming, plural table, FK = <singular>_id
--   Mục 2: NOT NULL tối đa, TIMESTAMPTZ
--   Mục 4: GIST cho geometry, partial cho soft-delete
--   Mục 5: created_at / updated_at / deleted_at
--   Mục 6: UUID v4
--
-- Idempotent: chạy lại an toàn.
-- ============================================================================


-- ──────────────────────────────────────────────────────────────────────────
-- aoi_polygons — Vùng quan tâm (province / district) lấy từ OSM Overpass
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aoi_polygons (
    id              UUID                            NOT NULL DEFAULT uuid_generate_v4(),
    slug            VARCHAR(100)                    NOT NULL,    -- "danang", "hai_chau"
    name            VARCHAR(255)                    NOT NULL,    -- "Đà Nẵng"
    admin_level     SMALLINT                        NOT NULL,    -- OSM: 4=tỉnh/TP, 6=quận/huyện, 8=phường/xã
    osm_relation_id BIGINT,                                      -- traceability
    boundary        GEOMETRY(MULTIPOLYGON, 4326)    NOT NULL,
    properties      JSONB                           NOT NULL DEFAULT '{}'::jsonb,
    fetched_at      TIMESTAMPTZ                     NOT NULL,    -- timestamp khi fetch từ OSM

    created_at      TIMESTAMPTZ                     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ                     NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,

    CONSTRAINT pk_aoi_polygons              PRIMARY KEY (id),
    CONSTRAINT uq_aoi_polygons_slug         UNIQUE (slug),
    CONSTRAINT ck_aoi_polygons_admin_level  CHECK (admin_level BETWEEN 2 AND 12)
);

CREATE INDEX IF NOT EXISTS idx_aoi_polygons_boundary
    ON aoi_polygons USING GIST (boundary);

CREATE INDEX IF NOT EXISTS idx_aoi_polygons_admin_level
    ON aoi_polygons (admin_level)
    WHERE deleted_at IS NULL;


-- ──────────────────────────────────────────────────────────────────────────
-- Trigger updated_at — fn_set_updated_at đã được tạo ở 04_triggers.sql
-- ──────────────────────────────────────────────────────────────────────────
DROP TRIGGER IF EXISTS trg_aoi_polygons_set_updated_at ON aoi_polygons;
CREATE TRIGGER trg_aoi_polygons_set_updated_at
    BEFORE UPDATE ON aoi_polygons
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();