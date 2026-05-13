"""CLI: sinh đầy đủ biểu đồ đánh giá cho 1 model_version.

Usage:
    cd services/ml-service-predict
    uv run python -m evaluation.generate_report --version stage2-20260513T131351Z

Output: evaluation/reports/<model_version>/01_*.png .. 14_*.png + summary.txt.

Flags:
    --version   model_version (BẮT BUỘC, vd: stage2-20260513T131351Z)
    --skip      bỏ qua nhóm plot ("regression"|"classification"|"training"|"interpretation")
    --out       override output dir (default: evaluation/reports/<version>)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .data_loader import load_eval_bundle
from .plots import interpretation, regression, training_curve

log = logging.getLogger(__name__)

_PLOT_GROUPS = {
    "regression": regression.render,
    "training": training_curve.render,
    "interpretation": interpretation.render,
}


def _write_summary(bundle, out_dir: Path) -> None:
    """summary.txt — copy metrics + hyperparams từ meta.json để user khỏi mở JSON."""
    meta = bundle.meta
    metrics = meta["metrics"]
    split = meta.get("split", {})
    lines = [
        f"Stage 2 evaluation report — {bundle.model_version}",
        "=" * 60,
        "",
        "Dataset (spatial stratified hold-out)",
        f"  strategy          : {split.get('strategy', 'unknown')}",
        f"  cell_size_deg     : {split.get('cell_size_deg', 'n/a')}",
        f"  n_train_cells     : {split.get('n_train_cells', 'n/a')}",
        f"  n_test_cells      : {split.get('n_test_cells', 'n/a')}",
        f"  test_fraction     : target={split.get('test_fraction', 'n/a')} "
        f"actual={split.get('test_fraction_actual', 0.0):.3f}",
        f"  n_train_val       : {metrics['n_train_val']}",
        f"  n_test            : {metrics['n_test']}",
        f"  dataset_hash      : {meta['dataset_hash'][:12]}",
        "",
        "Metrics",
        f"  CV RMSE (mean)    : {metrics['cv_rmse_mean']:.3f} dB",
        f"  CV RMSE per fold  : {[round(x, 3) for x in metrics['cv_rmse_per_fold']]}",
        f"  Test RMSE         : {metrics['test_rmse']:.3f} dB (residual head)",
        f"  Test MAE          : {metrics['test_mae']:.3f} dB",
        f"  Test RMSE +guard  : {metrics.get('test_rmse_guardrail', float('nan')):.3f} dB",
        f"  Guardrail clipped : {metrics.get('n_guardrail_violations', 0)}/{metrics['n_test']}",
        "",
        "Hyperparameters (Optuna best)",
    ]
    for k, v in sorted(meta["hyperparams"].items()):
        lines.append(f"  {k:20s}: {v}")
    lines.append("")
    lines.append(f"Features ({len(meta['feature_columns'])})")
    for f in meta["feature_columns"]:
        lines.append(f"  - {f}")
    (out_dir / "summary.txt").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--version", required=True, help="model_version (vd: stage2-20260513T131351Z)"
    )
    parser.add_argument(
        "--skip",
        action="append",
        choices=list(_PLOT_GROUPS),
        default=[],
        help="Bỏ qua nhóm plot (lặp được). Vd: --skip training --skip interpretation",
    )
    parser.add_argument("--out", type=Path, help="Override output dir")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    out_dir = args.out or Path("evaluation/reports") / args.version
    out_dir.mkdir(parents=True, exist_ok=True)
    log.info("Output dir: %s", out_dir.resolve())

    bundle = load_eval_bundle(args.version)

    for group, render in _PLOT_GROUPS.items():
        if group in args.skip:
            log.info("Skip group: %s", group)
            continue
        log.info("Rendering group: %s", group)
        render(bundle, out_dir)

    _write_summary(bundle, out_dir)
    log.info("Done. Open %s for charts.", out_dir.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
