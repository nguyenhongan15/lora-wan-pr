"""Linking service — kết nối user web-app với external data sources.

Plan-auth-v1 §3.3. Deep module: 6 method ngoài, ẩn encryption (MultiFernet),
JSON serialisation, source registry dispatch, ownership check, audit log.

Stateless modulo `cipher` constructor param. Caller (`edge/deps`) khởi tạo
1 instance → process. Connection injection per-call (consistency với
IdentityService + sync/_upsert).

KHÔNG gọi sync orchestrator (plan §2 cấm cross-application-module call).
`set_contribution(true)` chỉ flip flag — Step 7 sẽ thêm trigger sync ở
edge layer hoặc qua scheduler riêng.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from cryptography.fernet import InvalidToken
from sqlalchemy import Connection, text

from ..identity import User
from ..sources import SourceAuthError, get_adapter
from ._crypto import CredentialCipher
from .errors import (
    CredentialTestFailedError,
    LinkedSourceNotFoundError,
    LinkingError,
)

logger = structlog.get_logger("lora_coverage_api.linking")


@dataclass(frozen=True)
class LinkedSource:
    """View của 1 row auth.linked_sources — KHÔNG bao giờ chứa credentials.

    Caller (UI) hiển thị status + contribute badges. credential blob nằm
    trong DB encrypted, chỉ decrypt khi sync orchestrator (Step 7) cần.
    """

    id: UUID
    user_id: UUID
    source_type: str
    label: str
    status: str  # 'active' | 'paused' | 'failed'
    contribute_to_community: bool
    contributed_at: datetime | None
    last_sync_at: datetime | None
    last_sync_error: str | None
    created_at: datetime


# ── SQL ──────────────────────────────────────────────────────────────────

_INSERT_LINKED_SOURCE = text("""
    INSERT INTO auth.linked_sources (
        user_id, source_type, label, credentials_encrypted
    )
    VALUES (:user_id, :source_type, :label, :credentials_encrypted)
    RETURNING id, user_id, source_type, label, status, contribute_to_community,
              contributed_at, last_sync_at, last_sync_error, created_at
""")

_SELECT_USER_SOURCES = text("""
    SELECT id, user_id, source_type, label, status, contribute_to_community,
           contributed_at, last_sync_at, last_sync_error, created_at
    FROM auth.linked_sources
    WHERE user_id = :user_id
    ORDER BY created_at ASC
""")

_DELETE_OWNED = text("""
    DELETE FROM auth.linked_sources
    WHERE id = :id AND user_id = :user_id
    RETURNING id
""")

_UPDATE_STATUS_OWNED = text("""
    UPDATE auth.linked_sources
    SET status = :status
    WHERE id = :id AND user_id = :user_id
    RETURNING id, user_id, source_type, label, status, contribute_to_community,
              contributed_at, last_sync_at, last_sync_error, created_at
""")

# `contributed_at` chỉ set khi enabled=true VÀ chưa từng set (COALESCE giữ
# giá trị cũ). User tắt rồi bật lại → contributed_at giữ thời điểm opt-in
# đầu tiên (audit trail).
_UPDATE_CONTRIBUTION_OWNED = text("""
    UPDATE auth.linked_sources
    SET contribute_to_community = :enabled,
        contributed_at = CASE
            WHEN :enabled AND contributed_at IS NULL THEN now()
            ELSE contributed_at
        END
    WHERE id = :id AND user_id = :user_id
    RETURNING id, user_id, source_type, label, status, contribute_to_community,
              contributed_at, last_sync_at, last_sync_error, created_at
""")


def _row_to_linked_source(row: Any) -> LinkedSource:
    return LinkedSource(
        id=row.id,
        user_id=row.user_id,
        source_type=row.source_type,
        label=row.label,
        status=row.status,
        contribute_to_community=row.contribute_to_community,
        contributed_at=row.contributed_at,
        last_sync_at=row.last_sync_at,
        last_sync_error=row.last_sync_error,
        created_at=row.created_at,
    )


class LinkingService:
    def __init__(self, *, cipher: CredentialCipher) -> None:
        self._cipher = cipher

    # ── public interface ──────────────────────────────────────────────────

    def test(self, source_type: str, credentials: dict[str, str]) -> None:
        """Validate credential bằng adapter.connect — KHÔNG persist.

        Không trả gì khi pass; raise nếu fail.

        Raises:
            UnknownSourceTypeError: source_type không có trong registry (400).
            CredentialTestFailedError: provider reject credential (400).
            SourceUnreachableError / SourceFetchError: provider down (502).
                Không convert sang CredentialTestFailedError vì lỗi không
                thuộc về credential — caller cần biết để retry.
        """
        adapter = get_adapter(source_type)
        try:
            adapter.connect(credentials)
        except SourceAuthError as exc:
            raise CredentialTestFailedError(
                f"Credential cho '{source_type}' bị provider từ chối"
            ) from exc

    def link(
        self,
        conn: Connection,
        user: User,
        source_type: str,
        label: str,
        credentials: dict[str, str],
    ) -> LinkedSource:
        """Validate credential → encrypt → insert. Atomic.

        Sau khi link: status='active' (default), contribute_to_community=false
        (privacy opt-in). User phải gọi `set_contribution(true)` riêng để
        opt-in đóng góp lên bản đồ cộng đồng.
        """
        # 1. Validate trước khi encrypt + insert. Fail-fast tránh lưu blob
        #    không decrypt nổi sau này.
        self.test(source_type, credentials)

        # 2. Encrypt + persist.
        blob = self._cipher.encrypt(credentials)
        row = conn.execute(
            _INSERT_LINKED_SOURCE,
            {
                "user_id": user.id,
                "source_type": source_type,
                "label": label,
                "credentials_encrypted": blob,
            },
        ).one()

        logger.info(
            "source_linked",
            user_id=str(user.id),
            linked_source_id=str(row.id),
            source_type=source_type,
        )
        return _row_to_linked_source(row)

    def unlink(self, conn: Connection, user: User, linked_source_id: UUID) -> None:
        """Hard delete row. Data đã đóng góp giữ lại với linked_source_id=NULL
        (migration 0007 ON DELETE SET NULL).

        Raises:
            LinkedSourceNotFoundError: id không tồn tại hoặc thuộc user khác.
        """
        result = conn.execute(
            _DELETE_OWNED,
            {"id": linked_source_id, "user_id": user.id},
        ).one_or_none()
        if result is None:
            raise LinkedSourceNotFoundError(f"Linked source {linked_source_id} không tồn tại")
        logger.info(
            "source_unlinked",
            user_id=str(user.id),
            linked_source_id=str(linked_source_id),
        )

    def list_for(self, conn: Connection, user: User) -> list[LinkedSource]:
        """Liệt kê tất cả linked sources của user. KHÔNG decrypt credentials."""
        rows = conn.execute(_SELECT_USER_SOURCES, {"user_id": user.id}).all()
        return [_row_to_linked_source(r) for r in rows]

    def set_sync_enabled(
        self, conn: Connection, user: User, linked_source_id: UUID, enabled: bool
    ) -> LinkedSource:
        """Toggle status active ↔ paused.

        KHÔNG cho phép set status='failed' qua API — đó là cờ kỹ thuật do
        sync orchestrator (Step 7) bật khi sync fail nhiều lần liên tiếp.
        """
        new_status = "active" if enabled else "paused"
        row = conn.execute(
            _UPDATE_STATUS_OWNED,
            {"id": linked_source_id, "user_id": user.id, "status": new_status},
        ).one_or_none()
        if row is None:
            raise LinkedSourceNotFoundError(f"Linked source {linked_source_id} không tồn tại")
        logger.info(
            "source_sync_status_changed",
            user_id=str(user.id),
            linked_source_id=str(linked_source_id),
            new_status=new_status,
        )
        return _row_to_linked_source(row)

    def set_contribution(
        self, conn: Connection, user: User, linked_source_id: UUID, enabled: bool
    ) -> LinkedSource:
        """Toggle `contribute_to_community`. KHÔNG trigger sync ở Step 6.

        Step 7 sẽ thêm trigger sync ở edge layer (hoặc scheduler) khi user
        bật contribute lần đầu — không gọi từ application module này
        (plan §2 cấm cross-module call).
        """
        row = conn.execute(
            _UPDATE_CONTRIBUTION_OWNED,
            {"id": linked_source_id, "user_id": user.id, "enabled": enabled},
        ).one_or_none()
        if row is None:
            raise LinkedSourceNotFoundError(f"Linked source {linked_source_id} không tồn tại")
        logger.info(
            "source_contribution_changed",
            user_id=str(user.id),
            linked_source_id=str(linked_source_id),
            enabled=enabled,
        )
        return _row_to_linked_source(row)

    # ── package-internal — Step 7 sync orchestrator dùng để decrypt ───────

    def _decrypt_credentials(self, blob: bytes) -> dict[str, str]:
        """Decrypt credential blob. KHÔNG public — chỉ Step 7 sync gọi qua
        wrapper trong service module riêng; tránh leak credential ra route.
        """
        try:
            return self._cipher.decrypt(blob)
        except InvalidToken as exc:
            raise LinkingError(
                "Không decrypt được credential — key đã rotate ra ngoài key list?"
            ) from exc


__all__ = ["LinkedSource", "LinkingService"]
