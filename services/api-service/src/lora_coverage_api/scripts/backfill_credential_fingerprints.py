"""Backfill credential_fingerprint cho row legacy (NULL) trong auth.linked_sources.

Chạy 1 lần sau migration 0009. Mục đích: enforce UNIQUE
`(source_type, credential_fingerprint)` trên cả row đã link trước migration
— nếu không, 2 user link cùng account, 1 row NULL + 1 row có fingerprint
sẽ KHÔNG conflict (UNIQUE PARTIAL `WHERE NOT NULL`).

Cách chạy:
    docker compose exec api-service \\
        python -m lora_coverage_api.scripts.backfill_credential_fingerprints

Idempotent: chỉ động row có fingerprint NULL. Chạy lại không tác dụng phụ.

Conflict handling: nếu 2 row legacy NULL refer cùng 1 account, row 2 update
sẽ vi phạm UNIQUE → script log skip, không raise. Hệ quả: row đầu được tag
fingerprint, row sau giữ NULL — admin tự quyết định xoá hay giữ. Mục tiêu
chính (chặn link MỚI cùng account) vẫn đạt vì row đầu đã có fingerprint.
"""

from __future__ import annotations

import logging
import sys
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..application.linking import CredentialCipher
from ..application.sources import get_adapter
from ..config import Settings
from ..infrastructure.db import make_engine

logger = logging.getLogger("backfill_fingerprints")

_SELECT_NULL = text("""
    SELECT id, source_type, credentials_encrypted
    FROM auth.linked_sources
    WHERE credential_fingerprint IS NULL
    ORDER BY created_at
""")

_UPDATE_FINGERPRINT = text("""
    UPDATE auth.linked_sources
    SET credential_fingerprint = :fp
    WHERE id = :id AND credential_fingerprint IS NULL
""")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings()
    cipher = CredentialCipher(keys=settings.linking_fernet_keys_list)
    engine = make_engine(settings.database_url)

    with engine.begin() as conn:
        rows = conn.execute(_SELECT_NULL).all()

    logger.info("found %d row(s) with NULL fingerprint", len(rows))
    updated = 0
    skipped_conflict = 0
    skipped_error = 0

    for row in rows:
        ls_id: UUID = row.id
        source_type: str = row.source_type
        blob: bytes = row.credentials_encrypted

        try:
            credentials = cipher.decrypt(blob)
            adapter = get_adapter(source_type)
            canonical = adapter.canonicalize_credentials(credentials)
            fp = cipher.fingerprint(canonical)
        except Exception as exc:  # log + skip, không break loop
            logger.warning("skip %s: derive fingerprint failed: %s", ls_id, exc)
            skipped_error += 1
            continue

        # UPDATE riêng từng row trong transaction riêng để 1 conflict không
        # rollback cả batch.
        try:
            with engine.begin() as conn:
                conn.execute(_UPDATE_FINGERPRINT, {"id": ls_id, "fp": fp})
        except IntegrityError as exc:
            logger.warning(
                "skip %s (%s): fingerprint trùng row khác đã tag — admin review: %s",
                ls_id,
                source_type,
                exc.orig,
            )
            skipped_conflict += 1
            continue
        updated += 1
        logger.info("ok %s (%s)", ls_id, source_type)

    logger.info(
        "done: updated=%d skipped_conflict=%d skipped_error=%d",
        updated,
        skipped_conflict,
        skipped_error,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
