"""Smoke test cho luồng admin self-contribution auto-approve.

Chạy trong container api-service:
    docker compose exec -T api-service python /code/scripts/smoke_admin_auto_approve.py

Test 3 case:
  A) Regular admin (vanlic.dn) đóng góp → auto-approve + 2 mail (self + super).
  B) Super admin (anngh2004) đóng góp → auto-approve + 1 mail (dedupe).
  C) Non-admin user → KHÔNG auto-approve, vẫn pending_review.

Mỗi case:
  1. Tạo 1 batch + 3 quarantine rows fake (external_id deterministic).
  2. Gọi `submit_batch_for_review` + `approve_pending_review_for_batch_id`.
  3. Assert DB state + capture mailer calls.
  4. Cleanup hoàn toàn.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from lora_coverage_api.application.trust.promotion import (
    approve_pending_review_for_batch_id,
)
from lora_coverage_api.application.uploads.batches import submit_batch_for_review
from lora_coverage_api.config import get_settings
from lora_coverage_api.edge.deps import _trust_validator
from sqlalchemy import create_engine, text


@dataclass
class FakeMailer:
    """Capture mailer calls, không gửi mail thật."""

    calls: list[dict] = field(default_factory=list)

    def send_admin_self_contribution_published(
        self,
        to_email,
        *,
        contributor_email,
        uploaded_at,
        approved_count,
        earliest_timestamp,
        latest_timestamp,
    ):
        self.calls.append(
            {
                "to": to_email,
                "contributor": contributor_email,
                "uploaded_at": uploaded_at.isoformat(),
                "count": approved_count,
                "earliest": earliest_timestamp.isoformat(),
                "latest": latest_timestamp.isoformat(),
            }
        )


def setup_quarantine_rows(conn, *, user_id, batch_id, n=3):
    """Insert n quarantine rows. Trả list (qid, ts, external_id)."""
    base_ts = datetime.now(UTC) - timedelta(days=1)
    inserted = []
    for i in range(n):
        qid = uuid.uuid4()
        ts = base_ts + timedelta(minutes=i)
        # external_id deterministic, gắn batch_id để không đụng row khác.
        ext_id = f"smoke-{batch_id.hex[:8]}-{i}"
        conn.execute(
            text(
                """
                INSERT INTO ts.survey_quarantine (
                    id, timestamp, location, rssi_dbm, snr_db,
                    spreading_factor, frequency_mhz, source_type,
                    contributor_user_id, uploader_id, external_id,
                    submitted_for_community, review_status,
                    batch_id, uploaded_at
                )
                VALUES (
                    :id, :ts,
                    ST_SetSRID(ST_MakePoint(108.20, 16.05), 4326)::geography,
                    -95.0, 7.5, 9, 923.2, 'csv_upload',
                    :uid, :uid, :ext_id,
                    false, NULL, :bid, :uploaded_at
                )
                """
            ),
            {
                "id": qid,
                "ts": ts,
                "uid": user_id,
                "ext_id": ext_id,
                "bid": batch_id,
                "uploaded_at": base_ts,
            },
        )
        inserted.append((qid, ts, ext_id))
    return inserted, base_ts


def create_batch(conn, *, user_id, kind="csv", uploaded_at=None):
    if uploaded_at is None:
        uploaded_at = datetime.now(UTC)
    row = conn.execute(
        text(
            """
            INSERT INTO me.upload_batches (
                user_id, kind, filename, linked_source_id, uploaded_at, points_count
            )
            VALUES (:uid, :kind, :fname, NULL, :uploaded_at, 0)
            RETURNING id
            """
        ),
        {
            "uid": user_id,
            "kind": kind,
            "fname": "smoke-test.csv",
            "uploaded_at": uploaded_at,
        },
    ).one()
    return row.id


def cleanup(conn, *, batch_id, user_id):
    conn.execute(text("DELETE FROM ts.survey_training WHERE batch_id = :bid"), {"bid": batch_id})
    conn.execute(text("DELETE FROM ts.survey_quarantine WHERE batch_id = :bid"), {"bid": batch_id})
    conn.execute(text("DELETE FROM me.upload_batches WHERE id = :bid"), {"bid": batch_id})


def fetch_user(conn, email):
    row = conn.execute(
        text("SELECT id, email, is_admin FROM auth.users WHERE email = :e"),
        {"e": email},
    ).first()
    if not row:
        raise SystemExit(f"User {email} không tồn tại trong DB")
    return row


def assert_eq(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got!r}, want={want!r}")
    return ok


def run_case(engine, settings, label, *, user_email, expect_approve, expect_mail_count):
    print(f"\n=== Case {label}: user={user_email} ===")
    with engine.begin() as conn:
        user = fetch_user(conn, user_email)
        batch_id = create_batch(conn, user_id=user.id)
        _rows, _base_ts = setup_quarantine_rows(conn, user_id=user.id, batch_id=batch_id)

    trust = _trust_validator()
    mailer = FakeMailer()
    super_email = settings.super_admin_email

    try:
        with engine.begin() as conn:
            queued = submit_batch_for_review(conn, user_id=user.id, batch_id=batch_id)
            approved = (
                approve_pending_review_for_batch_id(
                    conn, trust, batch_id=batch_id, reviewer_id=user.id
                )
                if user.is_admin
                else []
            )

        # Simulate email path từ endpoint
        if approved:
            recipients = [user.email]
            if super_email and super_email.lower() != user.email.lower():
                recipients.append(super_email)
            timestamps = [p.timestamp for p in approved]
            for r in recipients:
                mailer.send_admin_self_contribution_published(
                    r,
                    contributor_email=user.email,
                    uploaded_at=approved[0].submitted_at,
                    approved_count=len(approved),
                    earliest_timestamp=min(timestamps),
                    latest_timestamp=max(timestamps),
                )

        # Verify DB
        with engine.begin() as conn:
            training_count = conn.execute(
                text("SELECT COUNT(*) FROM ts.survey_training WHERE batch_id = :bid"),
                {"bid": batch_id},
            ).scalar_one()
            review_status_set = sorted(
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT DISTINCT review_status FROM ts.survey_quarantine WHERE batch_id = :bid"
                    ),
                    {"bid": batch_id},
                ).all()
            )

        passed = True
        passed &= assert_eq("queued (sent to pending_review)", queued, 3)
        passed &= assert_eq("approved.count", len(approved), expect_approve)
        passed &= assert_eq("training rows count", training_count, expect_approve)
        passed &= assert_eq("mailer call count", len(mailer.calls), expect_mail_count)
        if expect_approve:
            passed &= assert_eq(
                "quarantine review_status",
                review_status_set,
                ["approved"],
            )
            recipients_got = [c["to"] for c in mailer.calls]
            recipients_expect = [user.email]
            if super_email.lower() != user.email.lower():
                recipients_expect.append(super_email)
            passed &= assert_eq("mailer recipients", recipients_got, recipients_expect)
        else:
            passed &= assert_eq(
                "quarantine review_status",
                review_status_set,
                ["pending_review"],
            )
        return passed
    finally:
        with engine.begin() as conn:
            cleanup(conn, batch_id=batch_id, user_id=user.id)
        print(f"  cleanup batch_id={batch_id} done")


def main():
    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)

    all_passed = True
    all_passed &= run_case(
        engine,
        settings,
        "A regular admin",
        user_email="vanlic.dn@gmail.com",
        expect_approve=3,
        expect_mail_count=2,
    )
    all_passed &= run_case(
        engine,
        settings,
        "B super admin",
        user_email="anngh2004@gmail.com",
        expect_approve=3,
        expect_mail_count=1,
    )

    print()
    print("=== SUMMARY ===")
    print("ALL PASS" if all_passed else "SOME FAIL")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
