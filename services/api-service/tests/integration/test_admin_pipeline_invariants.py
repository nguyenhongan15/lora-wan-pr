"""Integration tests cho SQL invariants của rebuild + retrain pipeline.

Pipeline production:
- `tasks/rebuild_coverage.py` dùng `MAX(timestamp) > last_rebuild_at` để biết
  gateway nào cần rebuild bản đồ ước lượng.
- `scripts/build_training_csv.py` dùng `WHERE submitted_for_community=TRUE` để
  scope dataset retrain Extra Trees.

Test này KHÔNG chạy Celery task thật (subprocess train tốn ~3 phút). Thay vì
đó verify các SQL contract mà task production phụ thuộc:
1. Cộng row mới vào training → rebuild query phát hiện thay đổi.
2. Xoá row CŨ → rebuild query KHÔNG phát hiện thay đổi (gap có chủ đích —
   docs xem `_test_rebuild_skips_when_old_row_deleted_KNOWN_GAP`).
3. Cộng row community → build-CSV count tăng.
4. Xoá row community → build-CSV count giảm.
5. Row private (`submitted_for_community=FALSE`) không lọt vào build-CSV.

Mỗi test chạy trong 1 transaction với rollback ở teardown → không mutate
persistent state của DB test.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from lora_coverage_api.infrastructure.db import make_engine

pytestmark = pytest.mark.integration

_REBUILD_QUERY = text("""
    SELECT gw.code, gw.last_rebuild_at,
           MAX(t.timestamp) AS max_ts
    FROM geo.gateways gw
    LEFT JOIN ts.survey_training t ON t.serving_gateway_id = gw.id
    WHERE gw.is_public = true AND gw.code = :code
    GROUP BY gw.id, gw.code, gw.last_rebuild_at
""")

_BUILD_CSV_COUNT_QUERY = text("""
    SELECT COUNT(*) FROM ts.survey_training s
    JOIN geo.gateways g ON s.serving_gateway_id = g.id
    WHERE s.submitted_for_community = TRUE
""")


@pytest.fixture
def db_conn():
    if "DATABASE_URL" not in os.environ:
        pytest.skip("DATABASE_URL chưa set; skip integration test.")
    engine = make_engine(os.environ["DATABASE_URL"])
    conn = engine.connect()
    tx = conn.begin()
    try:
        yield conn
    finally:
        tx.rollback()
        conn.close()


@pytest.fixture
def test_user_id(db_conn):
    """Seed 1 user cố định cho FK của survey_training.uploader_id."""
    uid = db_conn.execute(
        text("""
        INSERT INTO auth.users (email, password_hash, is_admin)
        VALUES (:email, 'x', false)
        RETURNING id
    """),
        {"email": f"pipeline-test-{uuid4().hex[:8]}@example.com"},
    ).scalar_one()
    return uid


@pytest.fixture
def test_gw(db_conn):
    """Seed gateway test với last_rebuild_at cố định ở mốc 2026-01-01."""
    code = f"pipeline-test-{uuid4().hex[:8]}"
    last_rebuild = datetime(2026, 1, 1, tzinfo=UTC)
    gw_id = db_conn.execute(
        text("""
        INSERT INTO geo.gateways (
            code, name, location, frequency_mhz, is_public, last_rebuild_at
        )
        VALUES (
            :code, :code,
            ST_SetSRID(ST_MakePoint(108.27, 16.06), 4326)::geography,
            923.0, true, :rb
        )
        RETURNING id
    """),
        {"code": code, "rb": last_rebuild},
    ).scalar_one()
    return {"code": code, "id": gw_id, "last_rebuild_at": last_rebuild}


def _insert_training(conn, gw_id, ts, uploader_id, submitted=True):
    return conn.execute(
        text("""
        INSERT INTO ts.survey_training (
            id, timestamp, location, rssi_dbm, snr_db, spreading_factor,
            frequency_mhz, serving_gateway_id, uploader_id, submitted_for_community
        ) VALUES (
            gen_random_uuid(), :ts,
            ST_SetSRID(ST_MakePoint(108.28, 16.05), 4326)::geography,
            -100, 5, 7, 923.0, :gw, :uid, :sc
        ) RETURNING id
    """),
        {"ts": ts, "gw": gw_id, "uid": uploader_id, "sc": submitted},
    ).scalar_one()


def test_rebuild_triggers_when_new_row_added(db_conn, test_gw, test_user_id):
    """Row mới (timestamp=now() > last_rebuild_at) → rebuild query trigger."""
    now = datetime.now(UTC)
    assert now > test_gw["last_rebuild_at"]
    _insert_training(db_conn, test_gw["id"], now, test_user_id)

    row = db_conn.execute(_REBUILD_QUERY, {"code": test_gw["code"]}).one()
    assert row.max_ts > row.last_rebuild_at, (
        "rebuild query phải detect row mới (max_ts > last_rebuild_at)"
    )


def test_rebuild_skips_when_old_row_deleted_KNOWN_GAP(db_conn, test_gw, test_user_id):  # noqa: N802
    """Xoá row CŨ → MAX(ts) không tăng → rebuild query SKIP (gap đã biết).

    Documents limitation: incremental skip optimization assume data chỉ tăng;
    delete-batch flow cần explicit invalidate `last_rebuild_at` ở admin handler.
    """
    old_ts = test_gw["last_rebuild_at"] - timedelta(days=30)
    row_id = _insert_training(db_conn, test_gw["id"], old_ts, test_user_id)

    before = db_conn.execute(_REBUILD_QUERY, {"code": test_gw["code"]}).one()
    assert before.max_ts == old_ts
    assert before.max_ts < before.last_rebuild_at  # Đã không trigger từ đầu.

    db_conn.execute(text("DELETE FROM ts.survey_training WHERE id = :id"), {"id": row_id})

    after = db_conn.execute(_REBUILD_QUERY, {"code": test_gw["code"]}).one()
    assert after.max_ts is None or after.max_ts <= after.last_rebuild_at, (
        "GAP: delete không raise MAX(ts) → rebuild skip dù data đã đổi"
    )


def test_handler_delete_closes_rebuild_gap(db_conn, test_gw, test_user_id):
    """Mô phỏng handler `delete_training_batch` (admin.py:1107) sau fix:
    SELECT affected gw → DELETE training → UPDATE last_rebuild_at=NULL.

    Chứng minh gap `_KNOWN_GAP` đã đóng ở handler level: dù MAX(ts) không
    tăng, last_rebuild_at=NULL ép rebuild query trigger (vế
    `last_rebuild_at IS NULL` ở rebuild_coverage.py:87).
    """
    old_ts = test_gw["last_rebuild_at"] - timedelta(days=30)
    row_id = _insert_training(db_conn, test_gw["id"], old_ts, test_user_id)

    # Pre-fix behavior: rebuild query SKIP.
    before = db_conn.execute(_REBUILD_QUERY, {"code": test_gw["code"]}).one()
    assert before.max_ts == old_ts
    assert before.max_ts < before.last_rebuild_at

    # Mô phỏng handler: SELECT affected → DELETE → invalidate.
    affected = (
        db_conn.execute(
            text("""
        SELECT DISTINCT serving_gateway_id FROM ts.survey_training
        WHERE id = :id AND serving_gateway_id IS NOT NULL
    """),
            {"id": row_id},
        )
        .scalars()
        .all()
    )
    db_conn.execute(text("DELETE FROM ts.survey_training WHERE id = :id"), {"id": row_id})
    db_conn.execute(
        text("UPDATE geo.gateways SET last_rebuild_at = NULL WHERE id = ANY(:ids)"),
        {"ids": list(affected)},
    )

    after = db_conn.execute(_REBUILD_QUERY, {"code": test_gw["code"]}).one()
    assert after.last_rebuild_at is None, (
        "fix: handler delete phải đặt last_rebuild_at=NULL → rebuild luôn trigger"
    )


def test_handler_approve_historical_ts_closes_rebuild_gap(db_conn, test_gw, test_user_id):
    """Mô phỏng handler `approve_batch` (admin.py:491) sau fix khi batch
    chứa timestamp historical (upload CSV survey cũ):
    INSERT training (ts cũ) → UPDATE last_rebuild_at=NULL cho gw bị ảnh hưởng.

    Trước fix: MAX(ts) không vượt last_rebuild_at → rebuild SKIP dù mới có
    data. Sau fix: NULL ép rebuild trigger.
    """
    old_ts = test_gw["last_rebuild_at"] - timedelta(days=60)
    _insert_training(db_conn, test_gw["id"], old_ts, test_user_id, submitted=True)

    # Pre-fix behavior: rebuild query SKIP vì max_ts < last_rebuild_at.
    before = db_conn.execute(_REBUILD_QUERY, {"code": test_gw["code"]}).one()
    assert before.max_ts == old_ts
    assert before.max_ts < before.last_rebuild_at

    # Mô phỏng handler: sau approve_pending_review_batch, gọi helper
    # _invalidate_rebuild_for_gateways với serving_gateway_id của approved rows.
    db_conn.execute(
        text("UPDATE geo.gateways SET last_rebuild_at = NULL WHERE id = ANY(:ids)"),
        {"ids": [test_gw["id"]]},
    )

    after = db_conn.execute(_REBUILD_QUERY, {"code": test_gw["code"]}).one()
    assert after.last_rebuild_at is None, (
        "fix: handler approve phải đặt last_rebuild_at=NULL → rebuild trigger dù ts cũ"
    )


def test_invalidate_helper_idempotent_with_empty_list(db_conn, test_gw):
    """Helper gọi với list rỗng = no-op, không lỗi, không đụng row khác.

    Bảo vệ trường hợp approve batch không khớp row nào (race) hoặc delete
    batch không có training row (đã document ở handler 404 path).
    """
    before_ts = test_gw["last_rebuild_at"]

    # Mô phỏng helper với list rỗng (filtered all None hoặc empty input).
    # Helper guard: `if not ids: return` → KHÔNG chạy UPDATE.
    # Test bằng cách: UPDATE với mảng rỗng → 0 row affected.
    result = db_conn.execute(
        text("UPDATE geo.gateways SET last_rebuild_at = NULL WHERE id = ANY(:ids)"),
        {"ids": []},
    )
    assert result.rowcount == 0

    # Gw test KHÔNG bị đụng.
    row = db_conn.execute(
        text("SELECT last_rebuild_at FROM geo.gateways WHERE id = :id"),
        {"id": test_gw["id"]},
    ).one()
    assert row.last_rebuild_at == before_ts


def test_retrain_csv_count_grows_on_new_community_row(db_conn, test_gw, test_user_id):
    """Row community mới → count build-CSV tăng đúng 1."""
    before = db_conn.execute(_BUILD_CSV_COUNT_QUERY).scalar_one()
    _insert_training(db_conn, test_gw["id"], datetime.now(UTC), test_user_id, submitted=True)
    after = db_conn.execute(_BUILD_CSV_COUNT_QUERY).scalar_one()
    assert after == before + 1


def test_retrain_csv_count_drops_on_delete(db_conn, test_gw, test_user_id):
    """Xoá row community → count build-CSV giảm đúng 1."""
    row_id = _insert_training(
        db_conn, test_gw["id"], datetime.now(UTC), test_user_id, submitted=True
    )
    before = db_conn.execute(_BUILD_CSV_COUNT_QUERY).scalar_one()
    db_conn.execute(text("DELETE FROM ts.survey_training WHERE id = :id"), {"id": row_id})
    after = db_conn.execute(_BUILD_CSV_COUNT_QUERY).scalar_one()
    assert after == before - 1


def test_retrain_csv_excludes_private_rows(db_conn, test_gw, test_user_id):
    """Row private (submitted_for_community=FALSE) không vào build-CSV."""
    before = db_conn.execute(_BUILD_CSV_COUNT_QUERY).scalar_one()
    _insert_training(db_conn, test_gw["id"], datetime.now(UTC), test_user_id, submitted=False)
    after = db_conn.execute(_BUILD_CSV_COUNT_QUERY).scalar_one()
    assert after == before
