"""
services/coverage_optimizer.py — Greedy MCLP / LSCP cost-aware optimization.

Phase v3.1 step 7.

Algorithms:
  - MCLP (Maximum Coverage Location Problem) fixed-K:
      Chọn K candidates maximize Σ_j w_j × max_{i∈S} P_ij.
  - LSCP (Location Set Covering Problem) target-%:
      Chọn min K sao cho Σ_j w_j × max_{i∈S} P_ij ≥ target × Σ_j w_j.

Cả 2 dùng greedy heuristic với tiêu chí cost-aware (default):
  Mỗi iter pick candidate i maximizes (marginal_gain / cost_i).

Tuân thủ:
  - SOLID SRP: pure compute, không đụng DB. optimization_repo.py lo persistence.
  - rulemonitoringlogging: 1 INFO log/solve với full metrics; DEBUG cho per-iter.
  - rulebackuprecovery: deterministic compute → recovery = re-solve với cùng
    matrix + costs + params. correlation_id passes through.

Sparse matrix optimization: truy cập trực tiếp `matrix.indptr / indices / data`
để evaluate marginal gain trong O(nnz_per_row) thay vì O(N_demand).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import csr_matrix

from services.coverage_matrix import CoverageMatrix

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Cost clamp tối thiểu cho ratio gain/cost — chống divide-by-zero
_MIN_COST_FOR_RATIO = 0.01

# LSCP safety: nếu target không reachable, dừng sau N iter để tránh vòng lặp vô hạn
DEFAULT_K_SAFETY_MAX = 50


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SelectionStep:
    """1 candidate được chọn trong greedy iteration."""
    rank:          int       # 1-based
    candidate_id:  str       # UUID của candidate
    candidate_idx: int       # row index trong matrix (debug only)
    marginal_gain: float     # weighted coverage gain so với covered hiện tại
    cost:          float


@dataclass(frozen=True)
class OptimizationResult:
    """Kết quả 1 lần solve. Frozen → immutable, dễ hash + persist."""
    mode:              str    # "mclp" | "lscp"
    selections:        list[SelectionStep]
    total_coverage_w:  float  # tổng weighted coverage đạt được
    coverage_ratio:    float  # = total_coverage_w / total_demand_weight
    total_cost:        float
    n_iterations:      int    # số lần loop greedy thực sự chạy
    compute_ms:        float
    cost_aware:        bool

    @property
    def n_selected(self) -> int:
        return len(self.selections)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def solve_mclp(
    matrix: CoverageMatrix,
    costs:  np.ndarray,
    *,
    k_max:          int,
    cost_aware:     bool = True,
    correlation_id: str | None = None,
) -> OptimizationResult:
    """
    Greedy MCLP fixed-K. Stop sau k_max iters HOẶC khi không còn positive gain.

    Args:
        matrix: CoverageMatrix từ coverage_matrix module.
        costs:  np.ndarray indexed cùng order với matrix.candidate_ids.
        k_max:  số candidate tối đa cần chọn.
        cost_aware: True = pick max(gain/cost); False = pick max(gain).
        correlation_id: trace ID xuyên qua services.

    Raises:
        ValueError nếu k_max <= 0 hoặc costs lệch shape với matrix.
    """
    if k_max <= 0:
        raise ValueError(f"k_max phải > 0, got {k_max}")
    return _greedy_solve(
        matrix, costs,
        mode="mclp", max_iter=k_max, target_coverage=None,
        cost_aware=cost_aware, correlation_id=correlation_id,
    )


def solve_lscp(
    matrix: CoverageMatrix,
    costs:  np.ndarray,
    *,
    target_coverage: float,
    k_safety_max:    int = DEFAULT_K_SAFETY_MAX,
    cost_aware:      bool = True,
    correlation_id:  str | None = None,
) -> OptimizationResult:
    """
    Greedy LSCP. Stop khi coverage_ratio ≥ target HOẶC k_safety_max iters.

    Args:
        target_coverage: target ratio (0, 1].
        k_safety_max: upper bound (chống infinite loop nếu target unreachable).
    """
    if not 0 < target_coverage <= 1:
        raise ValueError(
            f"target_coverage phải trong (0, 1], got {target_coverage}"
        )
    if k_safety_max <= 0:
        raise ValueError(f"k_safety_max phải > 0, got {k_safety_max}")
    return _greedy_solve(
        matrix, costs,
        mode="lscp", max_iter=k_safety_max, target_coverage=target_coverage,
        cost_aware=cost_aware, correlation_id=correlation_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Core greedy loop
# ─────────────────────────────────────────────────────────────────────────────

def _greedy_solve(
    matrix: CoverageMatrix,
    costs:  np.ndarray,
    *,
    mode:             str,
    max_iter:         int,
    target_coverage:  float | None,
    cost_aware:       bool,
    correlation_id:   str | None,
) -> OptimizationResult:
    """Common greedy loop dùng cho cả MCLP và LSCP."""
    t_start = time.perf_counter()

    sparse: csr_matrix = matrix.matrix
    n_cand, n_dem = sparse.shape

    if costs.shape != (n_cand,):
        raise ValueError(
            f"costs shape {costs.shape} không khớp matrix rows {n_cand}"
        )

    weights      = matrix.demand_weights.astype(np.float64)
    total_weight = float(weights.sum())

    if total_weight <= 0 or n_cand == 0 or n_dem == 0 or sparse.nnz == 0:
        # Empty / no coverage → return empty result
        logger.warning(
            "optimizer.no_solvable_input",
            extra={
                "correlationId": correlation_id,
                "mode":          mode,
                "nCand":         n_cand,
                "nDemand":       n_dem,
                "matrixNnz":     sparse.nnz,
                "totalWeight":   total_weight,
            },
        )
        return OptimizationResult(
            mode=mode, selections=[],
            total_coverage_w=0.0, coverage_ratio=0.0, total_cost=0.0,
            n_iterations=0, compute_ms=0.0, cost_aware=cost_aware,
        )

    # Sparse access — direct CSR arrays cho O(nnz_per_row) inspection
    indptr  = sparse.indptr
    indices = sparse.indices
    data    = sparse.data

    # State
    covered = np.zeros(n_dem, dtype=np.float64)   # max P over selected so far
    selected_mask = np.zeros(n_cand, dtype=bool)
    selections: list[SelectionStep] = []
    total_cost = 0.0

    # Cost vector clamp cho ratio
    costs_for_ratio = np.maximum(costs.astype(np.float64), _MIN_COST_FOR_RATIO)

    n_iterations = 0
    for k in range(max_iter):
        n_iterations += 1
        best_gain  = 0.0
        best_score = -np.inf
        best_i     = -1

        # Evaluate marginal gain mỗi candidate chưa chọn
        for i in range(n_cand):
            if selected_mask[i]:
                continue
            row_start = indptr[i]
            row_end   = indptr[i + 1]
            if row_start == row_end:
                continue   # row rỗng = candidate không phủ gì

            cols = indices[row_start:row_end]
            vals = data[row_start:row_end]

            # Marginal gain = Σ w_j × max(0, P_new - P_current)
            current = covered[cols]
            increment = vals - current
            increment[increment < 0] = 0.0
            gain = float((increment * weights[cols]).sum())

            if gain <= 0:
                continue

            score = (gain / costs_for_ratio[i]) if cost_aware else gain
            if score > best_score:
                best_score = score
                best_gain  = gain
                best_i     = i

        if best_i < 0:
            # No positive gain còn lại
            logger.debug(
                "optimizer.no_more_gain",
                extra={"correlationId": correlation_id, "iter": k + 1},
            )
            break

        # Commit selection best_i
        row_start = indptr[best_i]
        row_end   = indptr[best_i + 1]
        cols = indices[row_start:row_end]
        vals = data[row_start:row_end]
        covered[cols] = np.maximum(covered[cols], vals) 

        selected_mask[best_i] = True
        cand_id = matrix.candidate_ids[best_i]
        cost_i  = float(costs[best_i])
        total_cost += cost_i

        selections.append(SelectionStep(
            rank          = len(selections) + 1,
            candidate_id  = cand_id,
            candidate_idx = best_i,
            marginal_gain = best_gain,
            cost          = cost_i,
        ))

        coverage_w = float((covered * weights).sum())
        coverage_ratio = coverage_w / total_weight

        logger.debug(
            "optimizer.iteration",
            extra={
                "correlationId":      correlation_id,
                "iter":               k + 1,
                "selectedIdx":        best_i,
                "selectedId":         cand_id[:8],
                "marginalGain":       round(best_gain, 4),
                "cost":               cost_i,
                "coverageRatioSoFar": round(coverage_ratio, 4),
            },
        )

        # LSCP stopping criterion
        if target_coverage is not None and coverage_ratio >= target_coverage:
            break

    # Final metrics
    final_coverage_w  = float((covered * weights).sum())
    final_ratio       = final_coverage_w / total_weight if total_weight > 0 else 0.0
    compute_ms        = (time.perf_counter() - t_start) * 1000

    # LSCP unreachable warning
    if (mode == "lscp" and target_coverage is not None
            and final_ratio < target_coverage):
        logger.warning(
            "optimizer.lscp_target_unreachable",
            extra={
                "correlationId":    correlation_id,
                "targetCoverage":   target_coverage,
                "achievedCoverage": round(final_ratio, 4),
                "kSelected":        len(selections),
                "kSafetyMax":       max_iter,
            },
        )

    # Single INFO event với full audit metrics (RED + custom)
    logger.info(
        "optimizer.solved",
        extra={
            "correlationId":   correlation_id,
            "mode":            mode,
            "kRequested":      max_iter,
            "targetCoverage":  target_coverage,
            "kSelected":       len(selections),
            "totalCoverageW":  round(final_coverage_w, 4),
            "coverageRatio":   round(final_ratio, 4),
            "totalCost":       round(total_cost, 3),
            "nIterations":     n_iterations,
            "computeMs":       round(compute_ms, 1),
            "costAware":       cost_aware,
            "configHash":      matrix.config.short_hash(),
        },
    )

    return OptimizationResult(
        mode             = mode,
        selections       = selections,
        total_coverage_w = final_coverage_w,
        coverage_ratio   = final_ratio,
        total_cost       = total_cost,
        n_iterations     = n_iterations,
        compute_ms       = compute_ms,
        cost_aware       = cost_aware,
    )