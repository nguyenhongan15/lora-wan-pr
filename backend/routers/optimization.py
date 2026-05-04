"""
routers/optimization.py — Optimization endpoints (sync compute + DB persist).

Endpoints:
  POST   /api/v1/optimization-runs                 — trigger MCLP/LSCP
  GET    /api/v1/aois/{slug}/optimization-runs     — list paginated
  GET    /api/v1/optimization-runs/{run_id}        — detail
  DELETE /api/v1/optimization-runs/{run_id}        — soft-delete

Phase 10 changes (surgical):
  - Build CoverageConfig với environment_type (truyền từ payload hoặc default 'urban')
  - Gọi resolve_calibrated_params() trước compute → snapshot calibrated params
  - Audit: calibration_id được embed vào coverage_config JSON khi persist

Dùng:
  - core.responses.ok
  - core.exceptions.NotFoundError, AppError
  - request.state.request_id (CorrelationIdMiddleware)
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, Query, Request
from shapely.wkt import loads as wkt_loads
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppError, NotFoundError
from core.responses import ok
from database import AsyncSessionLocal
from schemas import (
    OptimizationRunCreate,
    OptimizationRunDetail,
    OptimizationRunSummary,
    SelectionDetailOutput,
)
from services import candidate_repo
from services.coverage_matrix import (
    CandidatePoint,
    CoverageConfig,
    get_or_compute_coverage_matrix,
    resolve_calibrated_params,
)
from services.coverage_optimizer import solve_lscp, solve_mclp
from services.grid import make_adaptive_demand_grid
from services.optimization_repo import (
    get_optimization_run,
    save_optimization_run,
    soft_delete_optimization_run,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["optimization"])


# ─── DB dependency ───────────────────────────────────────────────────────────

async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _derive_warnings(row: dict[str, Any]) -> list[str]:
    """Tạo warnings (vd LSCP target không đạt) cho FE hiển thị."""
    out: list[str] = []
    if row["mode"] == "lscp" and row.get("target_coverage") is not None:
        target   = float(row["target_coverage"])
        achieved = float(row["coverage_ratio"])
        if achieved < target:
            out.append(
                f"LSCP target {target * 100:.1f}% không đạt; "
                f"K={row['n_selected']} candidates phủ {achieved * 100:.2f}%"
            )
    return out


def _row_to_summary(row: dict[str, Any]) -> OptimizationRunSummary:
    return OptimizationRunSummary(
        id                   = row["id"],
        mode                 = row["mode"],
        k_max                = row["k_max"],
        target_coverage      = float(row["target_coverage"]) if row.get("target_coverage") is not None else None,
        cost_aware           = row["cost_aware"],
        coverage_config_hash = row["coverage_config_hash"],
        n_selected           = row["n_selected"],
        coverage_ratio       = float(row["coverage_ratio"]),
        total_cost           = float(row["total_cost"]),
        compute_ms           = row["compute_ms"],
        correlation_id       = row.get("correlation_id"),
        notes                = row.get("notes"),
        created_at           = row["created_at"],
        warnings             = _derive_warnings(row),
    )


def _row_to_detail(row: dict[str, Any]) -> OptimizationRunDetail:
    selections = [
        SelectionDetailOutput.model_validate(s)
        for s in (row.get("selection_details") or [])
    ]
    return OptimizationRunDetail(
        id                   = row["id"],
        aoi_id               = row["aoi_id"],
        mode                 = row["mode"],
        k_max                = row["k_max"],
        target_coverage      = float(row["target_coverage"]) if row.get("target_coverage") is not None else None,
        cost_aware           = row["cost_aware"],
        coverage_config      = row["coverage_config"],
        coverage_config_hash = row["coverage_config_hash"],
        selection_details    = selections,
        n_selected           = row["n_selected"],
        total_coverage_w     = float(row["total_coverage_w"]),
        coverage_ratio       = float(row["coverage_ratio"]),
        total_cost           = float(row["total_cost"]),
        n_iterations         = row["n_iterations"],
        compute_ms           = row["compute_ms"],
        correlation_id       = row.get("correlation_id"),
        notes                = row.get("notes"),
        created_at           = row["created_at"],
        updated_at           = row["updated_at"],
        warnings             = _derive_warnings(row),
    )


async def _load_aoi_row(
    db: AsyncSession, slug: str,
) -> dict[str, Any] | None:
    row = (await db.execute(text("""
        SELECT id::text AS id, ST_AsText(boundary) AS wkt
        FROM aoi_polygons
        WHERE slug = :slug AND deleted_at IS NULL
    """), {"slug": slug})).mappings().first()
    return dict(row) if row else None


# ─── POST /optimization-runs (sync) ─────────────────────────────────────────

@router.post("/optimization-runs", status_code=201)
async def create_optimization_run(
    payload: OptimizationRunCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Sync compute → persist → return full detail."""
    cid = getattr(request.state, "request_id", None)

    # 1. Load AOI (full + optional urban)
    full_row = await _load_aoi_row(db, payload.aoi_slug)
    if full_row is None:
        raise NotFoundError(
            f"Không tìm thấy AOI với slug '{payload.aoi_slug}'",
            code="AOI_NOT_FOUND",
        )
    aoi_id    = full_row["id"]
    full_poly = wkt_loads(full_row["wkt"])

    urban_poly = None
    if payload.urban_slug:
        urban_row = await _load_aoi_row(db, payload.urban_slug)
        if urban_row is None:
            raise NotFoundError(
                f"Không tìm thấy AOI urban với slug '{payload.urban_slug}'",
                code="AOI_NOT_FOUND",
            )
        urban_poly = wkt_loads(urban_row["wkt"])

    # 2. Candidates
    cands_dict = await candidate_repo.list_candidates_by_aoi_slug(db, payload.aoi_slug)
    if not cands_dict:
        raise AppError(
            f"AOI '{payload.aoi_slug}' không có candidates. "
            f"Chạy candidate_bootstrap.py trước.",
            code="NO_CANDIDATES",
            http_status=400,
        )
    candidates = [
        CandidatePoint(
            id   = c["id"],
            lat  = float(c["lat"]),
            lng  = float(c["lng"]),
            cost = float(c["cost"]),
        )
        for c in cands_dict
    ]

    # 3. Demand grid (on-the-fly, không persist)
    demand = make_adaptive_demand_grid(full_poly, urban_poly)

    # 4. Build CoverageConfig (Pydantic input → dataclass)
    cc = payload.coverage_config

    # environment_type: priority = payload.coverage_config.environment_type
    #                              > payload-level default 'urban'
    # Pydantic schema có thể CHƯA có field này → dùng getattr fallback an toàn
    env_type = getattr(cc, "environment_type", None) or "urban"

    config = CoverageConfig(
        model                = cc.model,
        frequency_mhz        = cc.frequency_mhz,
        sf                   = cc.sf,
        tx_power_dbm         = cc.tx_power_dbm,
        tx_antenna_height_m  = cc.tx_antenna_height_m,
        rx_antenna_height_m  = cc.rx_antenna_height_m,
        tx_antenna_gain_dbi  = cc.tx_antenna_gain_dbi,
        rx_antenna_gain_dbi  = cc.rx_antenna_gain_dbi,
        r_max_m              = cc.r_max_m,
        min_coverage_prob    = cc.min_coverage_prob,
        environment_type     = env_type,
    )

    # 4b. Resolve calibrated params (no-op nếu model != 'calibrated')
    #     Nếu fallback Hata được trigger → config.model bị thay từ 'calibrated' → 'hata'.
    config = await resolve_calibrated_params(db, config, correlation_id=cid)

    # 5. Coverage matrix (cached)
    matrix = get_or_compute_coverage_matrix(
        candidates, demand, config, correlation_id=cid,
    )

    # 6. Solve
    costs = np.array([c.cost for c in candidates], dtype=np.float64)
    if payload.mode == "mclp":
        result = solve_mclp(
            matrix, costs,
            k_max=payload.k_max,
            cost_aware=payload.cost_aware,
            correlation_id=cid,
        )
    else:  # lscp
        result = solve_lscp(
            matrix, costs,
            target_coverage=payload.target_coverage,
            k_safety_max=payload.k_safety_max,
            cost_aware=payload.cost_aware,
            correlation_id=cid,
        )

    # 7. Persist (config có chứa calibration_id snapshot → audit reproducible)
    run_id = await save_optimization_run(
        db,
        aoi_id          = aoi_id,
        mode            = payload.mode,
        k_max           = payload.k_max,
        target_coverage = payload.target_coverage,
        cost_aware      = payload.cost_aware,
        coverage_config = config,
        result          = result,
        correlation_id  = cid,
        notes           = payload.notes,
    )

    # 8. Re-fetch + serialize
    row = await get_optimization_run(db, run_id)
    if row is None:
        raise AppError(
            "Lưu run thành công nhưng đọc lại không được",
            code="PERSIST_INCONSISTENT",
            http_status=500,
        )
    detail = _row_to_detail(row)
    return ok(data=detail.model_dump(by_alias=True))


# ─── GET /aois/{slug}/optimization-runs (paginated) ─────────────────────────

@router.get("/aois/{slug}/optimization-runs")
async def list_runs_for_aoi(
    slug: str,
    request: Request,
    page:  int = Query(1,  ge=1),
    limit: int = Query(20, ge=1, le=100),
    mode:  Optional[str] = Query(None, pattern="^(mclp|lscp)$"),
    db: AsyncSession = Depends(get_db),
):
    """List recent runs cho 1 AOI. Sort created_at DESC."""
    aoi = await _load_aoi_row(db, slug)
    if aoi is None:
        raise NotFoundError(
            f"Không tìm thấy AOI với slug '{slug}'",
            code="AOI_NOT_FOUND",
        )

    where_mode = "AND r.mode = :mode" if mode else ""
    params: dict[str, Any] = {"slug": slug}
    if mode:
        params["mode"] = mode

    total_row = (await db.execute(text(f"""
        SELECT COUNT(*) AS cnt
        FROM optimization_runs r
        JOIN aoi_polygons a ON a.id = r.aoi_id
        WHERE a.slug = :slug
          AND a.deleted_at IS NULL
          AND r.deleted_at IS NULL
          {where_mode}
    """), params)).mappings().first()
    total = int(total_row["cnt"]) if total_row else 0

    offset = (page - 1) * limit
    params_paged = dict(params, limit=limit, offset=offset)
    rows = (await db.execute(text(f"""
        SELECT
            r.id::text                AS id,
            r.aoi_id::text            AS aoi_id,
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
        LIMIT :limit OFFSET :offset
    """), params_paged)).mappings().all()

    summaries = [_row_to_summary(dict(r)) for r in rows]
    return ok(
        data=[s.model_dump(by_alias=True) for s in summaries],
        meta={"page": page, "limit": limit, "total": total},
    )


# ─── GET /optimization-runs/{run_id} ────────────────────────────────────────

@router.get("/optimization-runs/{run_id}")
async def get_run(
    run_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    row = await get_optimization_run(db, run_id)
    if row is None:
        raise NotFoundError(
            f"Không tìm thấy optimization run id='{run_id}'",
            code="OPTIMIZATION_RUN_NOT_FOUND",
        )
    detail = _row_to_detail(row)
    return ok(data=detail.model_dump(by_alias=True))


# ─── DELETE /optimization-runs/{run_id} ─────────────────────────────────────

@router.delete("/optimization-runs/{run_id}")
async def delete_run(
    run_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete: set deleted_at = NOW()."""
    cid = getattr(request.state, "request_id", None)
    deleted = await soft_delete_optimization_run(db, run_id, correlation_id=cid)
    if not deleted:
        raise NotFoundError(
            f"Không tìm thấy optimization run id='{run_id}'",
            code="OPTIMIZATION_RUN_NOT_FOUND",
        )
    return ok(data={"id": str(run_id), "deleted": True})