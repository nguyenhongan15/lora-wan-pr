"""Reset DB tới trạng thái pre-sync hợp lệ cho lpwanmapper.

Bối cảnh: Migration 0007 thêm provenance cột (external_id, source_type, ...)
vào geo.gateways + ts.survey_*. Data legacy có 4 cột này = NULL → sync
upsert sẽ KHÔNG match (partial UNIQUE chỉ index rows external_id IS NOT
NULL) → INSERT trùng.

Chiến lược chọn (option A — truncate):
  * geo.gateways  → UPDATE 11 row legacy: SET external_id=code,
                    source_type='lpwanmapper'. KHÔNG xoá vì code đã là
                    natural id (gatewayId từ seed_gateways.py).
  * ts.survey_*   → TRUNCATE cả quarantine + training. Data legacy là
                    test/webhook capture với PK uuid4 không reproducible;
                    sync_one_cli sẽ pull lại đầy đủ ~8838 row có
                    provenance đúng từ /data API.

DESTRUCTIVE — yêu cầu env BACKFILL_CONFIRM=truncate. Idempotent: chạy lại
chỉ no-op (gateways đã có external_id, ts.survey_* đã rỗng).

Usage:
    DATABASE_URL=postgresql+psycopg://... \\
    BACKFILL_CONFIRM=truncate \\
    uv run --project services/api-service python scripts/backfill_provenance.py
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text

_SOURCE_TYPE = "lpwanmapper"


def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL chưa set.", file=sys.stderr)
        return 2

    confirm = os.environ.get("BACKFILL_CONFIRM", "").strip().lower()
    if confirm != "truncate":
        print(
            "ERROR: BACKFILL_CONFIRM=truncate chưa set. Script này TRUNCATE "
            "ts.survey_quarantine + ts.survey_training. Set env để xác nhận.",
            file=sys.stderr,
        )
        return 2

    engine = create_engine(db_url, future=True)
    with engine.begin() as conn:
        # ── geo.gateways: gắn provenance cho 11 legacy row ─────────────────
        gw_res = conn.execute(
            text(
                """
                UPDATE geo.gateways
                SET external_id = code, source_type = :st
                WHERE source_type IS NULL AND external_id IS NULL
                """
            ),
            {"st": _SOURCE_TYPE},
        )
        print(f"[backfill] geo.gateways: {gw_res.rowcount} row updated (external_id := code)")

        # ── ts.survey_*: truncate sạch ─────────────────────────────────────
        # CASCADE không cần (training không FK quarantine), nhưng vẫn an toàn.
        q_before = conn.execute(text("SELECT count(*) FROM ts.survey_quarantine")).scalar_one()
        t_before = conn.execute(text("SELECT count(*) FROM ts.survey_training")).scalar_one()

        conn.execute(text("TRUNCATE ts.survey_quarantine"))
        conn.execute(text("TRUNCATE ts.survey_training"))

        print(f"[backfill] ts.survey_quarantine: TRUNCATE ({q_before} row removed)")
        print(f"[backfill] ts.survey_training:   TRUNCATE ({t_before} row removed)")

    print("[backfill] DONE - ready for scripts/sync_one_cli.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
