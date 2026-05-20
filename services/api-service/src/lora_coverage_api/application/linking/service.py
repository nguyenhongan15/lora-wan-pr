"""Linking service — kết nối user web-app với external data sources.

Plan-auth-v1 §3.3. Deep module: 6 method ngoài, ẩn encryption (MultiFernet),
JSON serialisation, source registry dispatch, ownership check, audit log.

Stateless modulo `cipher` constructor param. Caller (`edge/deps`) khởi tạo
1 instance → process. Connection injection per-call (consistency với
IdentityService + sync/_upsert).

KHÔNG gọi sync orchestrator (plan §2 cấm cross-application-module call).
`set_contribution(true)` flip flag + backfill quarantine→training cùng
transaction (plan §3.4 — data đã pull về phải hiện trên map ngay). Sync
mới sẽ tự routing dựa cờ qua SyncService — caller (FE/edge) trigger sync
sau toggle là tuỳ chọn để pull data MỚI (không phải lý do data cũ lên map).
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from cryptography.fernet import InvalidToken
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from ..identity import User
from ..sources import SourceAuthError, get_adapter
from ._crypto import CredentialCipher
from .errors import (
    CredentialAlreadyLinkedError,
    CredentialTestFailedError,
    LinkedSourceNotFoundError,
    LinkingError,
)

# Source types được cấp webhook URL khi link. Hiện chỉ chirpstack; mở rộng
# khi có provider khác push-based (Helium, TTN). Định nghĩa ở 1 chỗ thay vì
# rải kiểm tra `source_type == "chirpstack"` khắp service.
_WEBHOOK_SOURCE_TYPES: frozenset[str] = frozenset({"chirpstack"})

# secrets.token_urlsafe(32) → 43 ký tự base64url (~256-bit entropy). Đặt
# hằng tại đây để rotate_webhook + link dùng cùng nguồn random; KHÔNG hard-
# code length trong code logic (Ousterhout Ch9: 1 nguồn sự thật).
_WEBHOOK_TOKEN_BYTES = 32

logger = structlog.get_logger("lora_coverage_api.linking")


@dataclass(frozen=True)
class LinkedSource:
    """View của 1 row auth.linked_sources — KHÔNG bao giờ chứa credentials.

    Caller (UI) hiển thị status + contribute badges. credential blob nằm
    trong DB encrypted, chỉ decrypt khi sync orchestrator (Step 7) cần.

    `has_webhook_token`: chỉ check NOT NULL — hash bytes nằm trong DB,
    KHÔNG bao giờ ra interface (đẩy theo plaintext qua LinkResult chỉ
    1 lần lúc link/rotate).
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
    has_webhook_token: bool = False
    webhook_rotated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LinkResult:
    """Trả về cho caller khi link / rotate-webhook thành công.

    `webhook_token` plaintext CHỈ tồn tại trong response của `link()` hoặc
    `rotate_webhook()` — không lưu DB, không log. Caller (route) MUST
    forward đúng 1 lần và clear khỏi memory; không lưu vào session/cache.
    None cho source không hỗ trợ webhook (lpwanmapper, csv).
    """

    linked_source: LinkedSource
    webhook_token: str | None


# ── SQL ──────────────────────────────────────────────────────────────────

_INSERT_LINKED_SOURCE = text("""
    INSERT INTO auth.linked_sources (
        user_id, source_type, label, credentials_encrypted, credential_fingerprint,
        webhook_token_hash, webhook_rotated_at
    )
    VALUES (
        :user_id, :source_type, :label, :credentials_encrypted, :credential_fingerprint,
        :webhook_token_hash,
        CASE WHEN :webhook_token_hash IS NOT NULL THEN now() ELSE NULL END
    )
    RETURNING id, user_id, source_type, label, status, contribute_to_community,
              contributed_at, last_sync_at, last_sync_error, created_at,
              (webhook_token_hash IS NOT NULL) AS has_webhook_token,
              webhook_rotated_at
""")

_SELECT_USER_SOURCES = text("""
    SELECT id, user_id, source_type, label, status, contribute_to_community,
           contributed_at, last_sync_at, last_sync_error, created_at,
           (webhook_token_hash IS NOT NULL) AS has_webhook_token,
           webhook_rotated_at
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
              contributed_at, last_sync_at, last_sync_error, created_at,
              (webhook_token_hash IS NOT NULL) AS has_webhook_token,
              webhook_rotated_at
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
              contributed_at, last_sync_at, last_sync_error, created_at,
              (webhook_token_hash IS NOT NULL) AS has_webhook_token,
              webhook_rotated_at
""")

# Rotate webhook token — overwrite hash + bump rotated_at. Single UPDATE
# atomic: old token invalid ngay khi commit, không có window 2 token cùng
# valid (plan §"Rotate"). source_type assert ở Python tier để raise
# LinkingError (400) thay vì silently no-op.
_UPDATE_WEBHOOK_HASH_OWNED = text("""
    UPDATE auth.linked_sources
    SET webhook_token_hash = :h,
        webhook_rotated_at = now()
    WHERE id = :id AND user_id = :user_id
    RETURNING id, user_id, source_type, label, status, contribute_to_community,
              contributed_at, last_sync_at, last_sync_error, created_at,
              (webhook_token_hash IS NOT NULL) AS has_webhook_token,
              webhook_rotated_at
""")


# Backfill khi user opt-in lần đầu: copy mọi measurement đã sync vào quarantine
# sang training. Idempotent qua ON CONFLICT (user toggle off→on→off→on không
# nhân đôi rows). Plan §3.4 + a-philosophy §8 (pull complexity downwards):
# 1 SQL transactional, KHÔNG batching ở v1 (background queue đẩy sang v2).
#
# `SET LOCAL statement_timeout`: scope = transaction → revert tự động khi
# commit/rollback. 25s buffer dưới uvicorn 30s default → timeout fail rollback
# trước khi worker bị giết.
_SET_BACKFILL_TIMEOUT = text("SET LOCAL statement_timeout = '25s'")

_BACKFILL_QUARANTINE_TO_TRAINING = text("""
    INSERT INTO ts.survey_training (
        id, timestamp, location, rssi_dbm, snr_db,
        spreading_factor, frequency_mhz, device_id,
        serving_gateway_id, uploader_id,
        external_id, source_type, contributor_user_id, linked_source_id
    )
    SELECT
        gen_random_uuid(), timestamp, location, rssi_dbm, snr_db,
        spreading_factor, frequency_mhz, device_id,
        serving_gateway_id, uploader_id,
        external_id, source_type, contributor_user_id, linked_source_id
    FROM ts.survey_quarantine
    WHERE linked_source_id = :ls_id
      AND reject_reason IS NULL
      AND external_id IS NOT NULL
    ON CONFLICT (timestamp, source_type, external_id) WHERE external_id IS NOT NULL
    DO NOTHING
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
        has_webhook_token=bool(getattr(row, "has_webhook_token", False)),
        webhook_rotated_at=getattr(row, "webhook_rotated_at", None),
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
    ) -> LinkResult:
        """Validate credential → encrypt → insert. Atomic.

        Sau khi link: status='active' (default), contribute_to_community=false
        (privacy opt-in). User phải gọi `set_contribution(true)` riêng để
        opt-in đóng góp lên bản đồ cộng đồng.

        Source thuộc `_WEBHOOK_SOURCE_TYPES` (hiện chỉ chirpstack): sinh
        thêm webhook token + lưu hash; trả plaintext trong `LinkResult.
        webhook_token` (caller forward 1 lần cho user copy). Token KHÔNG
        bao giờ ghi DB hay log.

        Raises:
            CredentialTestFailedError: provider reject credential.
            CredentialAlreadyLinkedError: cùng external account (theo
                fingerprint) đã được user khác link — UNIQUE conflict.
        """
        # 1. Validate trước khi encrypt + insert. Fail-fast tránh lưu blob
        #    không decrypt nổi sau này.
        self.test(source_type, credentials)

        # 2. Encrypt + compute fingerprint. Fingerprint qua adapter — chỉ
        #    chứa field định danh (lpwan: email; chirpstack: api_url+token+
        #    tenant). UNIQUE (source_type, fingerprint) ở DB chặn dup.
        adapter = get_adapter(source_type)
        canonical = adapter.canonicalize_credentials(credentials)
        fingerprint = self._cipher.fingerprint(canonical)
        blob = self._cipher.encrypt(credentials)

        # 3. Webhook token cho push-based providers — sinh tại đây, hash đẩy
        #    cùng INSERT để row vừa tạo đã có token (1 transaction). Plaintext
        #    giữ ở scope local, return qua LinkResult, lifetime = response.
        webhook_token_plain: str | None = None
        webhook_token_hash: bytes | None = None
        if source_type in _WEBHOOK_SOURCE_TYPES:
            webhook_token_plain = secrets.token_urlsafe(_WEBHOOK_TOKEN_BYTES)
            webhook_token_hash = self._cipher.webhook_token_hash(webhook_token_plain)

        try:
            row = conn.execute(
                _INSERT_LINKED_SOURCE,
                {
                    "user_id": user.id,
                    "source_type": source_type,
                    "label": label,
                    "credentials_encrypted": blob,
                    "credential_fingerprint": fingerprint,
                    "webhook_token_hash": webhook_token_hash,
                },
            ).one()
        except IntegrityError as exc:
            # UNIQUE ux_linked_sources_fingerprint — không có UNIQUE nào khác
            # trên insert path nên catch generic IntegrityError là an toàn.
            raise CredentialAlreadyLinkedError(
                "Tài khoản này đã được người dùng khác liên kết"
            ) from exc

        logger.info(
            "source_linked",
            user_id=str(user.id),
            linked_source_id=str(row.id),
            source_type=source_type,
            webhook_token_issued=webhook_token_plain is not None,
        )
        return LinkResult(
            linked_source=_row_to_linked_source(row),
            webhook_token=webhook_token_plain,
        )

    def rotate_webhook(self, conn: Connection, user: User, linked_source_id: UUID) -> LinkResult:
        """Sinh webhook token mới + invalidate token cũ. Atomic.

        Source phải thuộc `_WEBHOOK_SOURCE_TYPES`. Sau commit: token cũ trả
        401 ở ingest endpoint (hash không match), token mới hoạt động ngay.
        UI hiển thị plaintext 1 lần duy nhất qua `LinkResult.webhook_token`.

        Raises:
            LinkedSourceNotFoundError: id không tồn tại / thuộc user khác.
            LinkingError: source_type không hỗ trợ webhook (vd lpwanmapper).
        """
        # Verify source_type qua 1 SELECT trước UPDATE — UPDATE conditional
        # trên source_type sẽ không phân biệt "không tồn tại" vs "tồn tại
        # nhưng không hỗ trợ webhook"; tách 2 query đổi 1 round-trip lấy
        # error message rõ ràng cho user.
        existing = conn.execute(
            text(
                "SELECT source_type FROM auth.linked_sources WHERE id = :id AND user_id = :user_id"
            ),
            {"id": linked_source_id, "user_id": user.id},
        ).one_or_none()
        if existing is None:
            raise LinkedSourceNotFoundError(f"Linked source {linked_source_id} không tồn tại")
        if existing.source_type not in _WEBHOOK_SOURCE_TYPES:
            raise LinkingError(f"Source type '{existing.source_type}' không hỗ trợ webhook ingest")

        new_token = secrets.token_urlsafe(_WEBHOOK_TOKEN_BYTES)
        new_hash = self._cipher.webhook_token_hash(new_token)
        row = conn.execute(
            _UPDATE_WEBHOOK_HASH_OWNED,
            {"id": linked_source_id, "user_id": user.id, "h": new_hash},
        ).one()

        logger.info(
            "webhook_token_rotated",
            user_id=str(user.id),
            linked_source_id=str(linked_source_id),
        )
        return LinkResult(
            linked_source=_row_to_linked_source(row),
            webhook_token=new_token,
        )

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

    def get(self, conn: Connection, user: User, linked_source_id: UUID) -> LinkedSource:
        """Lookup 1 linked source theo (id, owner). Raise nếu sai owner hoặc
        không tồn tại — gộp 2 case vào 1 LinkedSourceNotFoundError để không
        leak existence cho user khác.

        Dùng cho route cần ownership verify trước khi đọc resource liên đới
        (vd list devices của 1 source) — KHÔNG decrypt credentials.
        """
        row = conn.execute(
            text("""
                SELECT id, user_id, source_type, label, status, contribute_to_community,
                       contributed_at, last_sync_at, last_sync_error, created_at,
                       (webhook_token_hash IS NOT NULL) AS has_webhook_token,
                       webhook_rotated_at
                FROM auth.linked_sources
                WHERE id = :id AND user_id = :user_id
            """),
            {"id": linked_source_id, "user_id": user.id},
        ).one_or_none()
        if row is None:
            raise LinkedSourceNotFoundError(f"Linked source {linked_source_id} không tồn tại")
        return _row_to_linked_source(row)

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
        """Toggle `contribute_to_community`.

        enabled=true → backfill quarantine→training cho ls_id ngay trong cùng
        transaction. Plan §3.4: data đã pull về phải xuất hiện trên map cộng
        đồng ngay sau opt-in, KHÔNG đợi sync kế tiếp.

        Idempotent (ON CONFLICT DO NOTHING): toggle off→on→off→on không nhân
        đôi training rows. Không xoá khỏi training khi opt-out — privacy edge
        case này tách thành tác vụ riêng (không trong scope fix hiện tại).

        Sync mới (sau toggle) sẽ tự routing về training nhờ
        SyncService đọc `contribute_to_community` qua _LOCK_OWNED_ROW.
        """
        row = conn.execute(
            _UPDATE_CONTRIBUTION_OWNED,
            {"id": linked_source_id, "user_id": user.id, "enabled": enabled},
        ).one_or_none()
        if row is None:
            raise LinkedSourceNotFoundError(f"Linked source {linked_source_id} không tồn tại")

        if enabled:
            self._backfill_to_training(conn, user_id=user.id, ls_id=linked_source_id)

        logger.info(
            "source_contribution_changed",
            user_id=str(user.id),
            linked_source_id=str(linked_source_id),
            enabled=enabled,
        )
        return _row_to_linked_source(row)

    def _backfill_to_training(self, conn: Connection, *, user_id: UUID, ls_id: UUID) -> None:
        """INSERT...SELECT quarantine→training cho 1 linked_source. Audit-only:
        không trả gì, không raise (caller transaction wrap). Log row_count +
        duration_ms để observe (plan revisit a2 nếu >5% timeout)."""
        started = time.monotonic()
        conn.execute(_SET_BACKFILL_TIMEOUT)
        result = conn.execute(_BACKFILL_QUARANTINE_TO_TRAINING, {"ls_id": ls_id})
        row_count = result.rowcount
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "contribute_backfill_completed",
            user_id=str(user_id),
            linked_source_id=str(ls_id),
            row_count=row_count,
            duration_ms=duration_ms,
        )

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


__all__ = ["LinkedSource", "LinkingService", "LinkResult"]
