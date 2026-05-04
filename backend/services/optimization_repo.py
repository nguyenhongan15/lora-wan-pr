"""
services/optimization_repo.py — Persistence cho optimization_runs.

Phase v3.1 step 7.

Tuân thủ:
  - SOLID SRP: chỉ lo DB CRUD, không chứa logic optimizer.
  - rulefordesigndatabase mục 5: soft-delete (set deleted_at, không hard-delete).
  - rulebackuprecovery: snapshot candidate info ngay lúc save → audit-safe khi
    gateway_candidates bị regen sau này.
  - rulemonitoringlogging: log INFO khi save/delete thành công, ERROR khi fail.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.coverage_matrix import CoverageConfig
from services.coverage_optimizer import OptimizationResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Save
# ─────────────────────────────────────────────────────────────────────────────

async def save_optimization_run(
    db: AsyncSession,
    *,
    aoi_id:           uuid.UUID | str,
    mode:             str,
    k_max:            int | None,
    target_coverage:  float | None,
    cost_aware:       bool,
    coverage_config:  CoverageConfig,
    result:           OptimizationResult,
    correlation_id:   str | None = None,
    notes:            str | None = None,
) -> uuid.UUID:
    """
    Persist 1 optimization run.

    Snapshot candidate info (h3, lat, lng, cost, source) từ gateway_candidates
    tại thời điểm save → run history bất biến kể cả khi candidates regen.

    Returns:
        run_id (UUID).
    """
    # 1. Build selection_details với snapshot từ gateway_candidates
    selected_ids = [s.candidate_id for s in result.selections]

    cand_info: dict[str, dict[str, Any]] = {}
    if selected_ids:
        rows = (await db.execute(text("""
            SELECT
                id::text                          AS id,
                h3_index,
                ST_Y(location::geometry)          AS lat,
                ST_X(location::geometry)          AS lng,
                cost,
                source
            FROM gateway_candidates
            WHERE id = ANY(CAST(:ids AS uuid[]))
        """), {"ids": selected_ids})).mappings().all()
        cand_info = {r["id"]: dict(r) for r in rows}

    selection_details = []
    for s in result.selections:
        info = cand_info.get(s.candidate_id, {})
        selection_details.append({
            "rank":         s.rank,
            "candidateId":  s.candidate_id,
            "h3Index":      info.get("h3_index"),
            "lat":          float(info["lat"])  if info.get("lat")  is not None else None,
            "lng":          float(info["lng"])  if info.get("lng")  is not None else None,
            "cost":         float(info["cost"]) if info.get("cost") is not None else s.cost,
            "source":       info.get("source"),
            "marginalGain": s.marginal_gain,
        })

    # 2. Serialize coverage_config (dataclass → dict → JSON)
    coverage_config_json = json.dumps(dataclasses.asdict(coverage_config))

    # 3. Insert
    run_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO optimization_runs (
            id, aoi_id,
            mode, k_max, target_coverage, cost_aware,
            coverage_config, coverage_config_hash,
            selection_details,
            n_selected, total_coverage_w, coverage_ratio, total_cost,
            n_iterations, compute_ms,
            correlation_id, notes
        ) VALUES (
            :id, :aoi_id,
            :mode, :k_max, :target_coverage, :cost_aware,
            CAST(:coverage_config AS jsonb), :coverage_config_hash,
            CAST(:selection_details AS jsonb),
            :n_selected, :total_coverage_w, :coverage_ratio, :total_cost,
            :n_iterations, :compute_ms,
            :correlation_id, :notes
        )
    """), {
        "id":                   run_id,
        "aoi_id":               aoi_id,
        "mode":                 mode,
        "k_max":                k_max,
        "target_coverage":      target_coverage,
        "cost_aware":           cost_aware,
        "coverage_config":      coverage_config_json,
        "coverage_config_hash": coverage_config.short_hash(),
        "selection_details":    json.dumps(selection_details),
        "n_selected":           result.n_selected,
        "total_coverage_w":     result.total_coverage_w,
        "coverage_ratio":       result.coverage_ratio,
        "total_cost":           result.total_cost,
        "n_iterations":         result.n_iterations,
        "compute_ms":           int(result.compute_ms),
        "correlation_id":       correlation_id,
        "notes":                notes,
    })
    await db.commit()

    logger.info(
        "optimization_run.saved",
        extra={
            "correlationId":  correlation_id,
            "runId":          str(run_id),
            "aoiId":          str(aoi_id),
            "mode":           mode,
            "nSelected":      result.n_selected,
            "coverageRatio":  round(result.coverage_ratio, 4),
            "configHash":     coverage_config.short_hash(),
        },
    )
    return run_id


# ─────────────────────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────────────────────

async def get_optimization_run(
    db:     AsyncSession,
    run_id: uuid.UUID | str,
) -> dict | None:
    """
    Lấy full row 1 run. Trả None nếu không tồn tại hoặc đã soft-delete.
    """
    row = (await db.execute(text("""
        SELECT
            id::text                  AS id,
            aoi_id::text              AS aoi_id,
            mode,
            k_max,
            target_coverage,
            cost_aware,
            coverage_config,
            coverage_config_hash,
            selection_details,
            n_selected,
            total_coverage_w,
            coverage_ratio,
            total_cost,
            n_iterations,
            compute_ms,
            correlation_id,
            notes,
            created_at,
            updated_at
        FROM optimization_runs
        WHERE id = :id AND deleted_at IS NULL
    """), {"id": run_id})).mappings().first()
    return dict(row) if row else None


async def list_optimization_runs_by_aoi_slug(
    db:    AsyncSession,
    slug:  str,
    *,
    limit: int = 20,
    mode:  str | None = None,
) -> list[dict]:
    """
    List recent runs cho AOI (sort created_at DESC).

    Optional filter `mode` = 'mclp' | 'lscp'.
    """
    where_mode = "AND r.mode = :mode" if mode else ""
    params: dict[str, Any] = {"slug": slug, "limit": limit}
    if mode:
        params["mode"] = mode

    rows = (await db.execute(text(f"""
        SELECT
            r.id::text                AS id,
            r.mode,
            r.k_max,
            r.target_coverage,
            r.cost_aware,
            r.coverage_config_hash,
            r.n_selected,
            r.coverage_ratio,
            r.total_cost,
            r.compute_ms,
            r.correlation_id,
            r.notes,
            r.created_at
        FROM optimization_runs r
        JOIN aoi_polygons a ON a.id = r.aoi_id
        WHERE a.slug = :slug
          AND a.deleted_at IS NULL
          AND r.deleted_at IS NULL
          {where_mode}
        ORDER BY r.created_at DESC
        LIMIT :limit
    """), params)).mappings().all()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Soft-delete (rulefordesigndatabase mục 5)
# ─────────────────────────────────────────────────────────────────────────────

async def soft_delete_optimization_run(
    db:     AsyncSession,
    run_id: uuid.UUID | str,
    *,
    correlation_id: str | None = None,
) -> bool:
    """
    Soft-delete: set deleted_at = NOW(). Trả True nếu có row được update.
    """
    result = await db.execute(text("""
        UPDATE optimization_runs
        SET deleted_at = NOW()
        WHERE id = :id AND deleted_at IS NULL
    """), {"id": run_id})
    await db.commit()
    deleted = result.rowcount > 0

    logger.info(
        "optimization_run.soft_deleted",
        extra={
            "correlationId": correlation_id,
            "runId":         str(run_id),
            "found":         deleted,
        },
    )
    return deleted