"""CLI entry — `python -m scripts.train_stage2 [--promote] [--dry-run]`.

Wrap orchestrator.run_training() + log human-readable summary.

KHÔNG sinh biểu đồ evaluation — dùng `uv run python -m scripts.retrain_and_report`
ở repo root nếu muốn retrain + auto-render plots (gồm `comparison` group mới).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict

from lora_ml_predict.config import get_settings
from lora_ml_predict.training.retrain import run_retrain


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train Stage 2 LightGBM residual model.")
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Atomic-swap ml.active_models pointer ngay sau khi train (default: chỉ ghi run, không promote)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="DEBUG level logging",
    )
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    settings = get_settings()
    result = run_retrain(settings, auto_promote=args.promote)

    summary = asdict(result)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
