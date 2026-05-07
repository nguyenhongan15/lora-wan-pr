"""CLI demo cho Step 4 — pull từ lpwanmapper, upsert vào DB.

Plan-auth-v1 §11 step 4 exit criteria: "Demo: pull 1 lần thành công".

Flow:
  1. Load credential từ .env.lpwanmapper.local
  2. LpwanmapperSource.connect → token + gateways
  3. Trong 1 transaction:
       a. fetch_gateways → upsert vào geo.gateways, build map ext_id → uuid
       b. fetch_measurements → resolve gw uuid, upsert vào ts.survey_quarantine
  4. Print report (inserted/updated counts)

Idempotent: chạy lại nhiều lần không tạo duplicate (ON CONFLICT theo
(source_type, external_id) cho gateways, (timestamp, source_type,
external_id) cho measurements).

KHÔNG có auth/linking ở Step 4 → contributor_user_id + linked_source_id
giữ NULL. Step 7 sẽ có sync orchestrator điền vào.

Usage:
    DATABASE_URL=postgresql+psycopg://... \\
    uv run --project services/api-service python scripts/sync_one_cli.py

Exit codes:
    0  thành công
    2  thiếu credential / DATABASE_URL
    3  SourceAuthError
    4  SourceUnreachableError
    5  SourceFetchError
    9  lỗi không lường trước
"""

from __future__ import annotations

import os
import sys
import traceback
from collections import Counter
from pathlib import Path
from time import perf_counter
from uuid import UUID

from sqlalchemy import create_engine

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env.lpwanmapper.local"

# Service uploader cố định cho data ingest từ source adapter (chưa có user
# thật ở Step 4). Trùng convention với backfill_rdt.py + seed_surveys_danang.
_SERVICE_UPLOADER = UUID("11111111-1111-1111-1111-111111111111")
_SOURCE_TYPE = "lpwanmapper"


def _load_creds() -> tuple[str, str]:
    if not ENV_FILE.exists():
        print(f"ERROR: thiếu {ENV_FILE.name}", file=sys.stderr)
        sys.exit(2)
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv(ENV_FILE, override=False)
    email = os.environ.get("LPWANMAPPER_EMAIL", "").strip()
    password = os.environ.get("LPWANMAPPER_PASSWORD", "").strip()
    if not email or not password:
        print("ERROR: LPWANMAPPER_EMAIL/PASSWORD trống.", file=sys.stderr)
        sys.exit(2)
    return email, password


def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL chưa set.", file=sys.stderr)
        return 2
    email, password = _load_creds()

    # Lazy import — chỉ load app deps sau khi pre-checks pass.
    from lora_coverage_api.application.sources import (  # noqa: PLC0415
        SourceAuthError,
        SourceFetchError,
        SourceUnreachableError,
        get_adapter,
    )
    from lora_coverage_api.application.sync import (  # noqa: PLC0415
        upsert_gateway,
        upsert_measurement,
    )

    src = get_adapter(_SOURCE_TYPE)
    print(f"[sync] adapter={type(src).__name__} uploader={_SERVICE_UPLOADER}")

    try:
        handle = src.connect({"email": email, "password": password})
    except SourceAuthError as e:
        print(f"[FAIL] auth: {e}", file=sys.stderr)
        return 3
    except SourceUnreachableError as e:
        print(f"[FAIL] network: {e}", file=sys.stderr)
        return 4
    except SourceFetchError as e:
        print(f"[FAIL] response: {e}", file=sys.stderr)
        return 5
    print("[sync] connected")

    engine = create_engine(db_url, future=True)
    t0 = perf_counter()
    with engine.begin() as conn:
        # ── gateways ───────────────────────────────────────────────────────
        gw_counts: Counter[str] = Counter()
        gw_uuid_by_ext: dict[str, UUID] = {}
        for gw in src.fetch_gateways(handle):
            status, gw_id = upsert_gateway(conn, gw, source_type=_SOURCE_TYPE)
            gw_counts[status] += 1
            gw_uuid_by_ext[gw.external_id] = gw_id
        print(
            f"[sync] gateways: {gw_counts['inserted']} inserted, "
            f"{gw_counts['updated']} updated, {len(gw_uuid_by_ext)} total"
        )

        # ── measurements ───────────────────────────────────────────────────
        m_counts: Counter[str] = Counter()
        skipped_no_gateway = 0
        try:
            for m in src.fetch_measurements(handle, since=None):
                gw_id = gw_uuid_by_ext.get(m.serving_gateway_external_id)
                if gw_id is None:
                    # Adapter trả gateway external_id không có trong /login
                    # response → bỏ qua, không break sync.
                    skipped_no_gateway += 1
                    continue
                status = upsert_measurement(
                    conn,
                    m,
                    source_type=_SOURCE_TYPE,
                    serving_gateway_id=gw_id,
                    uploader_id=_SERVICE_UPLOADER,
                )
                m_counts[status] += 1
        except SourceAuthError as e:
            print(f"[FAIL] /data auth expired mid-sync: {e}", file=sys.stderr)
            return 3
        except SourceUnreachableError as e:
            print(f"[FAIL] /data network: {e}", file=sys.stderr)
            return 4
        except SourceFetchError as e:
            print(f"[FAIL] /data response: {e}", file=sys.stderr)
            return 5

        print(
            f"[sync] measurements: {m_counts['inserted']} inserted, "
            f"{m_counts['updated']} updated"
        )
        if skipped_no_gateway:
            print(
                f"[sync]   [warn] {skipped_no_gateway} measurement skipped "
                "(serving gateway not in /login response)"
            )

    elapsed = perf_counter() - t0
    print(f"[sync] DONE in {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[sync] interrupted", file=sys.stderr)
        sys.exit(130)
    except Exception:  # noqa: BLE001
        print("[FAIL] unexpected:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(9)
