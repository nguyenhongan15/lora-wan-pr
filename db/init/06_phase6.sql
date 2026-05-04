-- ============================================================================
-- 06_phase6.sql — Phase 6: webhook retry tracking + prediction grid versioning
-- Idempotent — chạy lại an toàn.
-- ============================================================================


-- ──────────────────────────────────────────────────────────────────────────
-- 1. Webhook delivery retry — thêm các cột tracking
-- ──────────────────────────────────────────────────────────────────────────
ALTER TABLE webhook_deliveries
    ADD COLUMN IF NOT EXISTS attempt_no    SMALLINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS final_status  VARCHAR(20)
        CHECK (final_status IN ('pending', 'success', 'failed_giveup'))
        DEFAULT 'success';

-- Index cho job retry quét: WHERE final_status='pending' AND next_retry_at <= NOW()
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_retry_queue
    ON webhook_deliveries (next_retry_at)
    WHERE final_status = 'pending';


-- ──────────────────────────────────────────────────────────────────────────
-- 2. Prediction grid snapshots — version history
-- ──────────────────────────────────────────────────────────────────────────
-- Mỗi lần chạy /predict/run → snapshot grid hiện tại (nếu có) trước khi xoá
-- → cho phép rollback hoặc so sánh nội bộ campaign qua thời gian
CREATE TABLE IF NOT EXISTS prediction_grid_snapshots (
    id          UUID         NOT NULL DEFAULT uuid_generate_v4(),
    campaign_id UUID         NOT NULL,
    algorithm   VARCHAR(50)  NOT NULL,
    label       VARCHAR(255),     -- user-defined name
    grid_count  INTEGER      NOT NULL,
    avg_rssi    NUMERIC(6,2),
    min_rssi    NUMERIC(6,2),
    max_rssi    NUMERIC(6,2),
    payload     JSONB        NOT NULL,    -- {features: [...]}
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_prediction_grid_snapshots PRIMARY KEY (id),
    CONSTRAINT fk_prediction_grid_snapshots_campaigns FOREIGN KEY (campaign_id)
        REFERENCES campaigns(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_prediction_grid_snapshots_campaign_time
    ON prediction_grid_snapshots (campaign_id, created_at DESC);