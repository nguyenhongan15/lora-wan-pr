"""CLI ở REPO ROOT — retrain Stage 2 + auto-generate evaluation plots/diagnose.

Usage (chạy ở repo root, một dòng giống `npm run dev:web`):
    uv run python -m scripts.retrain_and_report             # retrain + plots (default)
    uv run python -m scripts.retrain_and_report --promote   # also flip active pointer
    uv run python -m scripts.retrain_and_report --skip-plots
    uv run python -m scripts.retrain_and_report --skip-diagnose

Flow:
    1. retrain.run_retrain(settings) → produces model_version + artifact.
    2. evaluation.generate_report.main(--version <model_version>)
    3. evaluation.diagnose.main(--version <model_version>)
    4. Print TrainingResult + reports dir path.

Tại sao đặt ở repo root (không phải services/ml-service-predict/scripts):
  - `settings.stage2_artifact_dir` default = "services/ml-service-predict/artifacts/stage2"
    là path repo-root-relative. Run từ root → resolve đúng, không cần os.chdir.
  - User gõ 1 lệnh duy nhất ở root (tương tự `npm run dev:web` ở monorepo).
  - `lora_ml_predict` package import được nhờ uv workspace; `evaluation/*` không
    cài như package nên thêm service src dir vào sys.path tại đây.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)


_REPO_ROOT = Path(__file__).resolve().parent.parent
_ML_PREDICT_DIR = _REPO_ROOT / "services" / "ml-service-predict"
# evaluation/* không phải installed package → cần thêm service dir vào sys.path
# để `from evaluation.generate_report import main` resolve được. Thêm CUỐI list
# (append) thay vì đầu để khỏi shadow package nào tên trùng.
if str(_ML_PREDICT_DIR) not in sys.path:
    sys.path.append(str(_ML_PREDICT_DIR))

from lora_ml_predict.config import get_settings  # noqa: E402
from lora_ml_predict.training.retrain import RetrainResult, run_retrain  # noqa: E402

_REPORTS_ROOT = _REPO_ROOT / "services" / "ml-service-predict" / "evaluation" / "reports"
_DIR_PATTERN = re.compile(r"^train_lan_(\d+)$")


def _next_report_dir() -> Path:
    r"""Trả `evaluation/reports/train_lan_N` với N = max(N hiện có) + 1.

    Scan thư mục anh em: regex `^train_lan_(\d+)$` → max → +1. Nếu chưa có thư
    mục nào → train_lan_1. Path absolute (anchor về repo root) — không phụ thuộc
    cwd lúc gọi script.
    """
    _REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    used: list[int] = []
    for p in _REPORTS_ROOT.iterdir():
        if not p.is_dir():
            continue
        m = _DIR_PATTERN.match(p.name)
        if m:
            used.append(int(m.group(1)))
    next_idx = (max(used) + 1) if used else 1
    return _REPORTS_ROOT / f"train_lan_{next_idx}"


def _write_metadata(out_dir: Path, result: RetrainResult, retrain_index: int) -> None:
    """Ghi metadata.txt — pin mapping train_lan_N ↔ model_version để tracing."""
    lines = [
        f"model_version: {result.model_version}",
        f"retrain_index: {retrain_index}",
        f"created_at: {datetime.now(tz=UTC).isoformat(timespec='seconds')}",
        f"cv_rmse_mean: {result.cv_rmse_mean:.3f} dB",
        f"test_rmse: {result.test_rmse:.3f} dB (residual head)",
        f"test_rmse_guardrail: {result.test_rmse_guardrail:.3f} dB",
        f"n_train_val: {result.n_train_val}",
        f"n_test: {result.n_test}",
        f"artifact_uri: {result.artifact_uri}",
        f"dataset_hash: {result.dataset_hash[:12]}",
    ]
    (out_dir / "metadata.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
    )


def _render_plots(
    model_version: str,
    out_dir: Path,
    skip_plots: bool,
    skip_diagnose: bool,
) -> Path | None:
    """Gọi 2 CLI module evaluation/* qua main() để reuse logic + log handler.

    Trả về out_dir nếu render ít nhất 1 nhóm — caller log path để user mở.
    Import muộn để retrain không phụ thuộc matplotlib/shap khi --skip-plots.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if not skip_plots:
        log.info("Generating regression/training/interpretation plots → %s", out_dir)
        from evaluation.generate_report import main as gen_main

        rc = gen_main(["--version", model_version, "--out", str(out_dir)])
        if rc != 0:
            log.error("generate_report failed (rc=%s)", rc)
            return None

    if not skip_diagnose:
        log.info("Generating diagnose plots → %s", out_dir)
        from evaluation.diagnose import main as diag_main

        rc = diag_main(["--version", model_version, "--out", str(out_dir)])
        if rc != 0:
            log.error("diagnose failed (rc=%s)", rc)
            return None

    return out_dir if (not skip_plots or not skip_diagnose) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Retrain Stage 2 (v2 pipeline) + auto-generate eval plots.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Atomic-swap ml.active_models pointer sau retrain (default: chỉ ghi run).",
    )
    parser.add_argument(
        "--skip-plots",
        action="store_true",
        help="Bỏ qua regression/training/interpretation plots.",
    )
    parser.add_argument(
        "--skip-diagnose",
        action="store_true",
        help="Bỏ qua diagnose plots (distribution + buckets + top outliers).",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="DEBUG level logging.")
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    settings = get_settings()
    out_dir = _next_report_dir()
    retrain_index = int(_DIR_PATTERN.match(out_dir.name).group(1))  # type: ignore[union-attr]
    log.info("Starting retrain (auto_promote=%s) → %s", args.promote, out_dir)
    result = run_retrain(settings, auto_promote=args.promote)
    log.info(
        "Retrain done: %s (CV RMSE=%.3f, Test RMSE=%.3f / +guard %.3f)",
        result.model_version,
        result.cv_rmse_mean,
        result.test_rmse,
        result.test_rmse_guardrail,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_metadata(out_dir, result, retrain_index)

    plot_ok = _render_plots(
        result.model_version,
        out_dir,
        args.skip_plots,
        args.skip_diagnose,
    )
    if plot_ok is None and not (args.skip_plots and args.skip_diagnose):
        log.error("Plot generation failed — xem log phía trên")

    summary = asdict(result)
    summary["retrain_index"] = retrain_index
    summary["plot_dir"] = str(out_dir.resolve())
    print(json.dumps(summary, indent=2, default=str))
    log.info("Reports ready → %s", out_dir.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
