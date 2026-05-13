"""ml schema + model_runs / active_models registry

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-13

Mục tiêu (theo plan-v1 §6):
  - Tạo schema `ml` cho registry artifact ML (Predict-ML + Map-ML).
  - `ml.model_runs`: lịch sử mọi lần train. Namespace bằng (domain, stage).
  - `ml.active_models`: pointer hiện hữu (1 row mỗi domain+stage).

Tuân `rule-design-database.md`:
  - BCNF (model_runs không có transitive dep).
  - NOT NULL by default.
  - TIMESTAMPTZ.
  - Surrogate UUID PK (UUIDv7 ở app layer; DB chỉ enforce uniqueness).
  - FK active_models → model_runs đảm bảo không trỏ tới run không tồn tại.

`domain` allowlist: ('predict', 'map') — chỉ 2 team được pre-register.
`stage` SMALLINT 1-3 (semantics khác nhau giữa Predict-ML vs Map-ML).
"""

from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ml;")
    op.execute(
        "COMMENT ON SCHEMA ml IS "
        "'Model registry: Predict-ML (domain=predict) + Map-ML (domain=map) artifact metadata';"
    )

    op.execute(
        """
        CREATE TABLE ml.model_runs (
          run_id            UUID PRIMARY KEY,
          domain            VARCHAR(16) NOT NULL
                            CHECK (domain IN ('predict','map')),
          stage             SMALLINT NOT NULL
                            CHECK (stage BETWEEN 1 AND 3),
          model_version     VARCHAR(64) NOT NULL,
          dataset_hash      CHAR(64) NOT NULL,
          trained_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
          artifact_uri      VARCHAR(512) NOT NULL,
          metrics_json      JSONB NOT NULL,
          hyperparams_json  JSONB NOT NULL,
          status            VARCHAR(16) NOT NULL
                            CHECK (status IN ('trained','promoted','archived','failed')),
          promoted_at       TIMESTAMPTZ,
          notes             VARCHAR(512),
          CONSTRAINT model_runs_unique_version UNIQUE (domain, stage, model_version)
        );
        """
    )
    op.execute(
        "COMMENT ON TABLE ml.model_runs IS "
        "'Lịch sử train (cả Predict-ML & Map-ML). 1 row = 1 lần train. "
        "Status promoted = active hiện tại; archived = đã rotate out.';"
    )
    # Index cho query "list model_runs theo domain+stage gần nhất"
    op.execute(
        "CREATE INDEX model_runs_domain_stage_trained_at_idx "
        "ON ml.model_runs (domain, stage, trained_at DESC);"
    )

    op.execute(
        """
        CREATE TABLE ml.active_models (
          domain            VARCHAR(16) NOT NULL
                            CHECK (domain IN ('predict','map')),
          stage             SMALLINT NOT NULL
                            CHECK (stage BETWEEN 1 AND 3),
          model_version     VARCHAR(64) NOT NULL,
          promoted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
          promoted_by       UUID REFERENCES auth.users(id),
          PRIMARY KEY (domain, stage),
          FOREIGN KEY (domain, stage, model_version)
            REFERENCES ml.model_runs(domain, stage, model_version)
        );
        """
    )
    op.execute(
        "COMMENT ON TABLE ml.active_models IS "
        "'Pointer tới active model. 1 row mỗi (domain, stage). "
        "Atomic swap = UPDATE 1 row trong 1 transaction.';"
    )


def downgrade() -> None:
    # CASCADE để drop FK constraint trước khi drop bảng.
    op.execute("DROP TABLE IF EXISTS ml.active_models;")
    op.execute("DROP TABLE IF EXISTS ml.model_runs;")
    op.execute("DROP SCHEMA IF EXISTS ml CASCADE;")
