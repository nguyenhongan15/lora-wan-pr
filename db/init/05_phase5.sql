-- ============================================================================
-- 05_phase5.sql — Phase 5 schema: outbound webhook subscriptions + deliveries
--
-- Tuân thủ rulefordesigndatabase.pdf:
--   Mục 1: bảng plural, PK=id, FK=<singular>_id, naming pk_/fk_/uq_/ck_/idx_
--   Mục 2: NOT NULL tối đa, TIMESTAMPTZ
--   Mục 4: index FK + composite + partial soft-delete
--   Mục 5: created_at / updated_at / deleted_at
--   Mục 6: UUID v4
--
-- Idempotent: dùng IF NOT EXISTS — chạy lại an toàn.
-- ============================================================================


-- ──────────────────────────────────────────────────────────────────────────
-- webhook_subscriptions — đăng ký nhận event outbound
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id          UUID         NOT NULL DEFAULT uuid_generate_v4(),
    project_id  UUID         NOT NULL,
    name        VARCHAR(255) NOT NULL,
    target_url  TEXT         NOT NULL,
    secret      VARCHAR(128) NOT NULL,    -- shared secret để HMAC sign payload
    event_types JSONB        NOT NULL DEFAULT '[]'::jsonb,  -- ["gateway.offline", ...]
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,

    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ,

    CONSTRAINT pk_webhook_subscriptions PRIMARY KEY (id),
    CONSTRAINT fk_webhook_subscriptions_projects FOREIGN KEY (project_id)
        REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT ck_webhook_subscriptions_target_url
        CHECK (target_url ~ '^https?://')
);

CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_project_id
    ON webhook_subscriptions(project_id);

CREATE INDEX IF NOT EXISTS idx_webhook_subscriptions_active
    ON webhook_subscriptions(project_id)
    WHERE deleted_at IS NULL AND is_active = TRUE;


-- ──────────────────────────────────────────────────────────────────────────
-- webhook_deliveries — log mỗi lần POST outbound
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id              UUID         NOT NULL DEFAULT uuid_generate_v4(),
    subscription_id UUID         NOT NULL,
    event_type      VARCHAR(100) NOT NULL,
    payload         JSONB        NOT NULL,
    status_code     SMALLINT,                 -- NULL nếu network error
    response_body   TEXT,
    error_message   TEXT,
    duration_ms     INTEGER,
    delivered_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_webhook_deliveries PRIMARY KEY (id),
    CONSTRAINT fk_webhook_deliveries_subscriptions FOREIGN KEY (subscription_id)
        REFERENCES webhook_subscriptions(id) ON DELETE CASCADE
);

-- Lookup theo subscription + thời gian (xem lịch sử delivery gần nhất)
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_sub_delivered
    ON webhook_deliveries(subscription_id, delivered_at DESC);


-- ──────────────────────────────────────────────────────────────────────────
-- Trigger updated_at — gắn vào fn_set_updated_at đã có ở 04_triggers.sql
-- ──────────────────────────────────────────────────────────────────────────
DROP TRIGGER IF EXISTS trg_webhook_subscriptions_set_updated_at
    ON webhook_subscriptions;

CREATE TRIGGER trg_webhook_subscriptions_set_updated_at
    BEFORE UPDATE ON webhook_subscriptions
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();