"""Backfill ts.survey_quarantine từ các file r-dt/response_*.json.

Replay ChirpStack uplinks qua ChirpstackWebhookService → idempotent insert.
Chạy lại nhiều lần KHÔNG tạo duplicate (dedup theo deduplicationId + rx_index).

Usage:
    DATABASE_URL=postgresql+psycopg://... \\
    BACKFILL_UPLOADER_ID=11111111-1111-1111-1111-111111111111 \\
    uv run --project services/api-service python scripts/backfill_rdt.py

Hoặc chỉ định 1 file cụ thể:
    BACKFILL_FILES=r-dt/response_1777987799162.json python scripts/backfill_rdt.py

Mặc định scan tất cả file `r-dt/response_*.json` (trừ file metadata _688423).

LƯU Ý: r-dt/response_..._688423.json là metadata (deviceNames/gateways/token),
KHÔNG PHẢI list uplinks → script tự skip nếu thấy field "gateways".
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

# api-service src được uv install editable; import trực tiếp.
from lora_coverage_api.application.chirpstack_webhook_service import (
    ChirpstackWebhookService,
)
from lora_coverage_api.domain.survey import UploaderId
from lora_coverage_api.infrastructure.db import make_engine
from lora_coverage_api.infrastructure.survey_repository_pg import PgSurveyRepository

REPO_ROOT = Path(__file__).resolve().parent.parent
RDT_DIR = REPO_ROOT / "r-dt"


def _candidate_files() -> list[Path]:
    explicit = os.environ.get("BACKFILL_FILES")
    if explicit:
        return [Path(p.strip()) for p in explicit.split(",") if p.strip()]
    return sorted(RDT_DIR.glob("response_*.json"))


def _is_uplink_array(payload: Any) -> bool:
    """Phân biệt uplink list vs file metadata (có 'gateways'/'deviceNames')."""
    if isinstance(payload, list):
        return True
    return False


def _process_file(
    path: Path,
    service: ChirpstackWebhookService,
    uploader: UploaderId,
) -> tuple[int, int, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not _is_uplink_array(payload):
        print(f"  skip metadata file: {path.name}")
        return 0, 0, 0

    accepted = 0
    inserted = 0
    rejected = 0
    for up in payload:
        if not isinstance(up, dict):
            rejected += 1
            continue
        r = service.ingest_uplink(up, uploader)
        accepted += r.accepted_count
        inserted += r.inserted_count
        rejected += r.rejected_count
    return accepted, inserted, rejected


def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL chưa set.", file=sys.stderr)
        return 2

    uploader_raw = os.environ.get("BACKFILL_UPLOADER_ID")
    if not uploader_raw:
        print(
            "ERROR: BACKFILL_UPLOADER_ID chưa set "
            "(uuid của uploader để gắn vào quarantine rows).",
            file=sys.stderr,
        )
        return 2
    try:
        uploader = UploaderId(UUID(uploader_raw))
    except ValueError as e:
        print(f"ERROR: BACKFILL_UPLOADER_ID không phải UUID: {e}", file=sys.stderr)
        return 2

    files = _candidate_files()
    if not files:
        print(f"Không tìm thấy file nào để backfill (RDT_DIR={RDT_DIR})")
        return 1

    engine = make_engine(db_url)
    repo = PgSurveyRepository(engine)
    service = ChirpstackWebhookService(repository=repo)

    total_acc = total_ins = total_rej = 0
    for f in files:
        if not f.exists():
            print(f"  warn: {f} không tồn tại, skip")
            continue
        acc, ins, rej = _process_file(f, service, uploader)
        print(f"  {f.name}: accepted={acc} inserted={ins} rejected={rej}")
        total_acc += acc
        total_ins += ins
        total_rej += rej

    print(
        f"\nTotal: accepted={total_acc}  inserted={total_ins}  rejected={total_rej}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
