-- ============================================================================
-- 09_phase9.sql — Phase 9 (v3.1 step 7): Optimization runs (MCLP / LSCP)
--
-- Mục đích lưu DB:
--   - Audit trail (rulebackuprecovery): mọi optimization run được lưu kèm
--     coverage_config snapshot → reproduce bất kỳ lúc nào.
--   - A/B testing scenarios (Persona 1, 7).
--   - Source data cho BoQ + report export (Persona 3, 7).
--
-- Tuân thủ rulefordesigndatabase:
--   - Mục 1: pk_/fk_/uq_/ck_/idx_ naming
--   - Mục 2: NOT NULL tối đa, TIMESTAMPTZ
--   - Mục 5: created_at / updated_at / deleted_at (soft-delete)
--   - Mục 6: UUID v4
--
-- Idempotent: chạy lại an toàn.
-- ============================================================================


CREATE TABLE IF NOT EXISTS optimization_runs (
    id                    UUID                   NOT NULL DEFAULT uuid_generate_v4(),
    aoi_id                UUID                   NOT NULL,

    -- Mode + constraints (input)
    mode                  VARCHAR(10)            NOT NULL,    -- 'mclp' | 'lscp'
    k_max                 SMALLINT,                            -- chỉ dùng cho mclp
    target_coverage       NUMERIC(5, 4),                       -- chỉ dùng cho lscp (0-1)
    cost_aware            BOOLEAN                NOT NULL DEFAULT TRUE,

    -- Coverage config snapshot (cho reproducibility — recovery rule)
    coverage_config       JSONB                  NOT NULL,
    coverage_config_hash  VARCHAR(8)             NOT NULL,    -- short hash để query/group

    -- Selection details — denormalized snapshot (audit-safe khi candidates regen)
    -- Format: [{rank, candidateId, h3Index, lat, lng, cost, source, marginalGain}, ...]
    -- ordered by rank ASC.
    selection_details     JSONB                  NOT NULL,

    -- Result aggregates
    n_selected            SMALLINT               NOT NULL,
    total_coverage_w      NUMERIC(14, 4)         NOT NULL,    -- weighted demand covered
    coverage_ratio        NUMERIC(5, 4)          NOT NULL,    -- 0-1
    total_cost            NUMERIC(10, 3)         NOT NULL,
    n_iterations          SMALLINT               NOT NULL,    -- số lần loop greedy
    compute_ms            INTEGER                NOT NULL,

    -- Audit (rulemonitoringlogging — correlation across services)
    correlation_id        VARCHAR(64),
    notes                 TEXT,

    created_at            TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
    deleted_at            TIMESTAMPTZ,

    CONSTRAINT pk_optimization_runs PRIMARY KEY (id),
    CONSTRAINT fk_optimization_runs_aoi_polygons FOREIGN KEY (aoi_id)
        REFERENCES aoi_polygons(id) ON DELETE CASCADE,

    CONSTRAINT ck_optimization_runs_mode
        CHECK (mode IN ('mclp', 'lscp')),
    CONSTRAINT ck_optimization_runs_mclp_k
        CHECK (mode <> 'mclp' OR (k_max IS NOT NULL AND k_max > 0)),
    CONSTRAINT ck_optimization_runs_lscp_target
        CHECK (mode <> 'lscp' OR
               (target_coverage IS NOT NULL
                AND target_coverage > 0 AND target_coverage <= 1)),
    CONSTRAINT ck_optimization_runs_n_selected
        CHECK (n_selected >= 0),
    CONSTRAINT ck_optimization_runs_coverage_ratio
        CHECK (coverage_ratio BETWEEN 0 AND 1),
    CONSTRAINT ck_optimization_runs_compute_ms
        CHECK (compute_ms >= 0)
);


-- Index phục vụ query phổ biến: list runs gần đây của 1 AOI (Persona 1, 3, 7)
CREATE INDEX IF NOT EXISTS idx_optimization_runs_aoi_created
    ON optimization_runs(aoi_id, created_at DESC)
    WHERE deleted_at IS NULL;

-- Filter theo mode (so sánh A/B)
CREATE INDEX IF NOT EXISTS idx_optimization_runs_mode
    ON optimization_runs(mode)
    WHERE deleted_at IS NULL;

-- Find runs với cùng config (group A/B testing)
CREATE INDEX IF NOT EXISTS idx_optimization_runs_config_hash
    ON optimization_runs(coverage_config_hash)
    WHERE deleted_at IS NULL;


-- Trigger updated_at — fn_set_updated_at đã có ở 04_triggers.sql
DROP TRIGGER IF EXISTS trg_optimization_runs_set_updated_at ON optimization_runs;
CREATE TRIGGER trg_optimization_runs_set_updated_at
    BEFORE UPDATE ON optimization_runs
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();