"""Persist artifact + ghi ml.model_runs + atomic-swap ml.active_models.

Plan v1 §4.4 + migration 0011.

Workflow (1 transaction):
  1. INSERT ml.model_runs (status='trained').
  2. UPDATE/INSERT ml.active_models (domain=predict, stage=2) → run_id mới.
  3. UPDATE ml.model_runs SET status='promoted' WHERE run_id = new.
  4. (Optional) status='archived' cho run cũ.

Atomic swap = 1 transaction theo migration 0011 comment. Caller gọi promote()
sau khi đã hoàn thành validation trên hold-out test set.

artifact_uri: local path tới joblib file (Q12 — R2 defer). Layout:
  {stage2_artifact_dir}/{model_version}/model.lgb
  {stage2_artifact_dir}/{model_version}/meta.json
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import psycopg

from ..config import Settings

log = logging.getLogger(__name__)

DOMAIN = "predict"
STAGE = 2  # Stage 2 = LightGBM residual (Predict-ML).


@dataclass(frozen=True, slots=True)
class ArtifactPaths:
    """File layout cho 1 model_version. Tất cả relative tới settings.stage2_artifact_dir."""

    root: Path
    model_file: Path  # *.lgb (LightGBM native format)
    meta_file: Path  # meta.json (feature names, hyperparams, metrics, dataset hash)


def _paths(settings: Settings, model_version: str) -> ArtifactPaths:
    root = settings.stage2_artifact_dir / model_version
    return ArtifactPaths(
        root=root,
        model_file=root / "model.lgb",
        meta_file=root / "meta.json",
    )


def save_artifact(
    settings: Settings,
    model_version: str,
    booster: lgb.Booster,
    meta: dict[str, Any],
) -> ArtifactPaths:
    """Ghi LightGBM booster + meta JSON xuống disk.

    Format LightGBM native (booster.save_model) thay vì joblib pickle:
    - cross-version stable (LightGBM tự deserialize),
    - human-readable text format → audit dễ.
    joblib cho meta dict thêm fallback nhưng JSON đủ.
    """
    paths = _paths(settings, model_version)
    paths.root.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(paths.model_file))
    paths.meta_file.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    log.info("Saved Stage 2 artifact: %s", paths.root)
    return paths


def load_booster(artifact_uri: str) -> lgb.Booster:
    """Load LightGBM booster từ file URI (local path).

    Q12 hiện tại = local; sau migrate R2 sẽ wrap URI parsing.
    """
    return lgb.Booster(model_file=artifact_uri)


def load_meta(artifact_uri: str) -> dict[str, Any]:
    """Load meta.json bên cạnh model file."""
    model_path = Path(artifact_uri)
    meta_path = model_path.parent / "meta.json"
    parsed: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
    return parsed


def _uuidv7() -> uuid.UUID:
    """UUIDv7 surrogate. Python stdlib chưa có v7, dùng v4 — registry không
    yêu cầu time-ordered ID (đã có trained_at TIMESTAMPTZ index).
    """
    return uuid.uuid4()


def insert_run(
    settings: Settings,
    model_version: str,
    dataset_hash: str,
    artifact_uri: str,
    metrics: dict[str, Any],
    hyperparams: dict[str, Any],
    notes: str | None = None,
) -> uuid.UUID:
    """INSERT ml.model_runs status='trained'. Return run_id.

    1 row mỗi train run. Không atomic-swap ở đây — caller gọi promote() riêng.
    """
    run_id = _uuidv7()
    with psycopg.connect(settings.db_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ml.model_runs (
              run_id, domain, stage, model_version, dataset_hash,
              artifact_uri, metrics_json, hyperparams_json, status, notes
            ) VALUES (
              %s, %s, %s, %s, %s,
              %s, %s::jsonb, %s::jsonb, 'trained', %s
            )
            """,
            (
                str(run_id),
                DOMAIN,
                STAGE,
                model_version,
                dataset_hash,
                artifact_uri,
                json.dumps(metrics),
                json.dumps(hyperparams),
                notes,
            ),
        )
        conn.commit()
    log.info("Inserted model_runs row: run_id=%s model_version=%s", run_id, model_version)
    return run_id


def promote(settings: Settings, model_version: str) -> None:
    """Atomic-swap active_models pointer → model_version mới.

    Transaction:
      1. UPDATE model_runs SET status='archived' WHERE đang promoted.
      2. UPDATE model_runs SET status='promoted', promoted_at=now() WHERE new.
      3. UPSERT active_models pointer.
    """
    with psycopg.connect(settings.db_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ml.model_runs
               SET status='archived'
             WHERE domain=%s AND stage=%s AND status='promoted'
            """,
            (DOMAIN, STAGE),
        )
        cur.execute(
            """
            UPDATE ml.model_runs
               SET status='promoted', promoted_at=now()
             WHERE domain=%s AND stage=%s AND model_version=%s
            """,
            (DOMAIN, STAGE, model_version),
        )
        cur.execute(
            """
            INSERT INTO ml.active_models (domain, stage, model_version, promoted_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (domain, stage) DO UPDATE
              SET model_version=EXCLUDED.model_version,
                  promoted_at=EXCLUDED.promoted_at
            """,
            (DOMAIN, STAGE, model_version),
        )
        conn.commit()
    log.info("Promoted active model: domain=%s stage=%d version=%s", DOMAIN, STAGE, model_version)


def get_active_model_version(settings: Settings) -> tuple[str, str] | None:
    """Read current active (model_version, artifact_uri). None nếu chưa promote.

    Dùng bởi serving server lúc startup để load đúng artifact.
    """
    with psycopg.connect(settings.db_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT am.model_version, mr.artifact_uri
              FROM ml.active_models am
              JOIN ml.model_runs mr USING (domain, stage, model_version)
             WHERE am.domain=%s AND am.stage=%s
            """,
            (DOMAIN, STAGE),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1])
