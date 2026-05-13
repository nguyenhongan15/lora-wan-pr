"""Load active Stage 2 model từ ml.active_models pointer.

What:
  load_active() → Stage2ResidualModel | None.
Hidden:
  SQL query, artifact path resolution, LightGBM load.
Failure mode:
  Chưa có active model → return None (caller fallback Stage1 only).
  Active row exists nhưng file disk thiếu → raise FileNotFoundError (boundary fail-fast).
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings
from ..stages.stage2_residual import Stage2ResidualModel, load_from_disk
from ..training.registry_writer import get_active_model_version

log = logging.getLogger(__name__)


def load_active(settings: Settings) -> Stage2ResidualModel | None:
    """Read DB pointer → load artifact. None khi chưa có model promoted.

    Lý do return None thay vì raise: lúc bootstrap (chưa train lần nào) serving
    server vẫn cần khởi động → trả Stage1-only response. Caller (server.py)
    log warning + tiếp tục.
    """
    info = get_active_model_version(settings)
    if info is None:
        log.warning("No active Stage 2 model in ml.active_models — Stage1 fallback only")
        return None
    model_version, artifact_uri = info

    if not Path(artifact_uri).exists():
        msg = (
            f"active model_version={model_version} points to missing file {artifact_uri}; "
            "registry/disk drift — investigate"
        )
        raise FileNotFoundError(msg)

    log.info("Loading active Stage 2 model: %s (%s)", model_version, artifact_uri)
    return load_from_disk(artifact_uri, model_version)
