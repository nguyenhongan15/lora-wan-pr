"""Sync orchestrator — pull data từ external source vào DB.

Plan-auth-v1 §3.4 + §10 + refactor 2026-06-11 (batch-based). Deep module:
2 method công khai (sync, sync_all_eligible) ẩn decrypt, adapter dispatch,
gateway external_id → uuid map, dedup loop, status update, audit log.

KHÔNG raise (plan §8.3): mọi failure → SyncResult.error. Caller (edge) chỉ
inspect `result.error is None` thay vì try/except. Riêng `LinkedSourceNotFoundError`
vẫn raise để edge map → 404 (route không tồn tại ≠ sync fail).

Cross-module (plan §2):
  * Sync KHÔNG gọi LinkingService. Cipher inject như primitive (DI từ edge).
  * Co-ownership cột linked_sources (post-mig 0024):
      - Sync owns: status, last_sync_at, last_sync_error
      - Linking owns: credentials_encrypted, label, source_type, user_id
    Schema change phải đụng cả 2 module — chấp nhận leakage hợp lý cho v1
    (plan §3.4 explicitly authorizes).

Concurrency (plan §10): same linked_source bị sync đồng thời → SELECT FOR UPDATE
SKIP LOCKED ở đầu sync(). Locked → SyncResult(error="sync_in_progress"), không
raise, không UPDATE status (giữ nguyên trạng thái ổn định).

Batch tracking (mig 0024): mỗi lần sync thành công đi qua bước measurement
ingest → tạo 1 row `me.upload_batches` kind=sync_<source_type>, filename =
ISO timestamp lúc click. Rows quarantine của sync này gắn batch_id để UI
"Quản lý dữ liệu" / "Lịch sử upload" gom đúng batch. Sync fail (decrypt
/ adapter error) trước measurement step → KHÔNG tạo batch (không có data).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from cryptography.fernet import InvalidToken
from sqlalchemy import Connection, text

from ...domain.survey import MAX_GATEWAY_DISTANCE_KM, haversine_km, is_in_vietnam
from ..identity import User
from ..linking import CredentialCipher, LinkedSourceNotFoundError
from ..sources import (
    DeviceRecord,
    GatewayRecord,
    SourceError,
    UnknownSourceTypeError,
    get_adapter,
)
from ..uploads import (
    UploadKind,
    add_batch_points_count,
    create_upload_batch,
    set_batch_points_count,
)
from ._upsert import (
    lookup_existing_gateway,
    upsert_device,
    upsert_gateway,
    upsert_gateway_quarantine,
    upsert_measurement,
)

logger = structlog.get_logger("lora_coverage_api.sync")


@dataclass(frozen=True)
class SyncResult:
    """Per-source result. `error is None` ↔ success.

    `gateways_quarantined` (mig 0029): số gateway mới đẩy vào quarantine chờ
    admin duyệt. KHÔNG cộng vào gateways_inserted (counter cũ chỉ đếm rows
    vào geo.gateways trực tiếp) để UI/log phân biệt hai con đường.
    """

    linked_source_id: UUID
    gateways_inserted: int
    gateways_updated: int
    gateways_quarantined: int
    measurements_inserted: int
    measurements_updated: int
    devices_inserted: int
    devices_updated: int
    last_sync_at: datetime | None
    error: str | None


@dataclass(frozen=True)
class SyncReport:
    """Aggregate kết quả của sync_all_eligible."""

    items: list[SyncResult]

    @property
    def successes(self) -> int:
        return sum(1 for r in self.items if r.error is None)

    @property
    def failures(self) -> int:
        return sum(1 for r in self.items if r.error is not None)


# ── Error sanitisation ───────────────────────────────────────────────────
# Truncate adapter exception messages trước khi log/persist. Adapter có thể
# leak hostname/URL/token trong text → cap 200 chars + dùng class name làm
# prefix định danh. Decrypt fail dùng constant string (không expose chi tiết).

_ERR_MSG_MAX = 200
_DECRYPT_ERR_TAG = "credential_decrypt_failed"
_LOCKED_ERR_TAG = "sync_in_progress"


def _sanitise_exc(exc: BaseException) -> str:
    return f"{exc.__class__.__name__}: {str(exc)[:_ERR_MSG_MAX]}"


# ── SQL ──────────────────────────────────────────────────────────────────
# Lock 1 row cho sync. SKIP LOCKED → row đang bị sync khác giữ → query trả
# 0 row, sync() phân biệt với "không tồn tại" bằng exists check riêng.

_LOCK_OWNED_ROW = text("""
    SELECT id, user_id, source_type, label,
           credentials_encrypted, status, last_sync_at
    FROM auth.linked_sources
    WHERE id = :id AND user_id = :user_id
    FOR UPDATE SKIP LOCKED
""")

_EXISTS_OWNED = text("""
    SELECT 1 FROM auth.linked_sources
    WHERE id = :id AND user_id = :user_id
""")

_UPDATE_SYNC_META = text("""
    UPDATE auth.linked_sources
    SET status = :status,
        last_sync_at = :last_sync_at,
        last_sync_error = :last_sync_error
    WHERE id = :id
""")

# Eligibility filter (post-mig 0024): chỉ sync source đang active + owner
# không bị disabled. Cờ contribute_to_community đã bỏ — quyết định đóng góp
# giờ per-batch (user bấm "Đóng góp" trên batch trong "Quản lý dữ liệu"),
# không còn per-source. JOIN users để áp disabled filter ở DB.
_SELECT_ELIGIBLE_IDS = text("""
    SELECT ls.id, ls.user_id
    FROM auth.linked_sources ls
    JOIN auth.users u ON u.id = ls.user_id
    WHERE ls.status = 'active'
      AND u.disabled = false
    ORDER BY ls.last_sync_at NULLS FIRST, ls.created_at ASC
""")

# Mapping source_type → upload_batches.kind. Khoá enum trong migration 0024
# chỉ 4 giá trị; sync source nào không trong map → skip batch creation
# (data vẫn vào quarantine với batch_id=NULL, không xuất hiện trong UI
# "Quản lý dữ liệu" nhưng không lỗi).
_SYNC_KIND: dict[str, UploadKind] = {
    "lpwanmapper": "sync_lpwanmapper",
    "chirpstack": "sync_chirpstack",
}


# ── Public service ───────────────────────────────────────────────────────


class SyncService:
    """Stateless module (cipher). Caller (edge/deps) khởi 1 instance / process.

    Post-mig 0024: bỏ trust injection — sync ghi thẳng quarantine với
    submitted_for_community=false, user bấm "Đóng góp" trên 1 batch ở UI
    "Quản lý dữ liệu" để gửi admin duyệt (xem application/uploads).
    """

    def __init__(self, *, cipher: CredentialCipher) -> None:
        self._cipher = cipher

    # ── single-source ────────────────────────────────────────────────────

    def sync(
        self,
        conn: Connection,
        *,
        user: User,
        linked_source_id: UUID,
        reuse_batch_id: UUID | None = None,
    ) -> SyncResult:
        """Pull 1 source. KHÔNG raise (trừ LinkedSourceNotFoundError → 404).

        Status update + audit log được commit cùng transaction của caller —
        caller dùng `engine.begin()` đảm bảo atomic.

        `reuse_batch_id` (live session): caller đã tạo batch trước (kind=
        'live_session') → skip create batch trong sync, dùng luôn batch_id
        đó cho `_ingest_measurements`. Mỗi sync incremental tiếp tục append
        row mới vào cùng batch thay vì tạo batch riêng.
        """
        params = {"id": linked_source_id, "user_id": user.id}
        row = conn.execute(_LOCK_OWNED_ROW, params).one_or_none()

        if row is None:
            # Phân biệt "không tồn tại / sai owner" (404) vs "đang lock" (200 + error)
            exists = conn.execute(_EXISTS_OWNED, params).one_or_none()
            if exists is None:
                raise LinkedSourceNotFoundError(f"Linked source {linked_source_id} không tồn tại")
            return SyncResult(
                linked_source_id=linked_source_id,
                gateways_inserted=0,
                gateways_updated=0,
                gateways_quarantined=0,
                devices_inserted=0,
                devices_updated=0,
                measurements_inserted=0,
                measurements_updated=0,
                last_sync_at=None,
                error=_LOCKED_ERR_TAG,
            )

        return self._run_locked(conn, user_id=user.id, row=row, reuse_batch_id=reuse_batch_id)

    # ── orchestration ────────────────────────────────────────────────────

    def sync_all_eligible(self, conn: Connection) -> SyncReport:
        """Iterate mọi linked_source eligible (plan §3.4). Dùng cho admin
        global sync (Step 8). Mỗi row lock riêng — locked rows skip silently
        (KHÔNG count vào failures vì là race nội bộ, không phải user error).
        """
        eligible = conn.execute(_SELECT_ELIGIBLE_IDS).all()
        results: list[SyncResult] = []
        for r in eligible:
            row = conn.execute(_LOCK_OWNED_ROW, {"id": r.id, "user_id": r.user_id}).one_or_none()
            if row is None:
                continue  # Race: another worker đang sync row này
            results.append(self._run_locked(conn, user_id=r.user_id, row=row))
        return SyncReport(items=results)

    # ── core (assumes row already locked) ────────────────────────────────

    def _run_locked(
        self,
        conn: Connection,
        *,
        user_id: UUID,
        row: Any,
        reuse_batch_id: UUID | None = None,
    ) -> SyncResult:
        started = time.monotonic()
        ls_id = row.id
        source_type = row.source_type
        log = logger.bind(
            user_id=str(user_id),
            linked_source_id=str(ls_id),
            source_type=source_type,
        )

        try:
            creds = self._decrypt(row.credentials_encrypted)
        except InvalidToken:
            # Lỗi vận hành (key rotated out / blob corrupt), KHÔNG phải user
            # error → log ở mức error để admin grep. Constant tag, không leak
            # exception detail xuống DB.
            log.error("credential_decrypt_failed")
            return self._finalise(
                conn,
                ls_id=ls_id,
                status="failed",
                error=_DECRYPT_ERR_TAG,
                log=log,
                started=started,
                counts=(0, 0, 0, 0, 0, 0, 0),
            )

        # Batch tracking (mig 0024): tạo batch row ngay trước measurement
        # ingest. Nếu source_type không có trong _SYNC_KIND (vd test source
        # tương lai), bỏ batch — data vẫn vào quarantine, chỉ không hiện
        # trong "Quản lý dữ liệu" UI. Filename = ISO timestamp click cho UX.
        # Live session (mig 0031): caller đã tạo batch kind='live_session'
        # từ trước → skip create, reuse batch_id để gom mọi sync incremental
        # vào 1 batch chung cho cả chuyến khảo sát.
        batch_id: UUID | None = reuse_batch_id
        if batch_id is None:
            kind = _SYNC_KIND.get(source_type)
            if kind is not None:
                batch_id, _ = create_upload_batch(
                    conn,
                    user_id=user_id,
                    kind=kind,
                    filename=datetime.now(UTC).isoformat(),
                    linked_source_id=ls_id,
                )

        try:
            adapter = get_adapter(source_type)
            handle = adapter.connect(creds)
            (
                gw_inserted,
                gw_updated,
                gw_quarantined,
                gw_uuid_by_external,
                gw_coords_by_external,
            ) = _ingest_gateways(
                conn,
                adapter,
                handle,
                source_type=source_type,
                user_id=user_id,
                ls_id=ls_id,
            )
            dev_inserted, dev_updated = _ingest_devices(
                conn,
                adapter,
                handle,
                source_type=source_type,
                user_id=user_id,
                ls_id=ls_id,
            )
            m_inserted, m_updated = _ingest_measurements(
                conn,
                adapter,
                handle,
                source_type=source_type,
                user_id=user_id,
                ls_id=ls_id,
                since=row.last_sync_at,
                gw_uuid_by_external=gw_uuid_by_external,
                gw_coords_by_external=gw_coords_by_external,
                batch_id=batch_id,
                log=log,
            )
        except (UnknownSourceTypeError, SourceError) as exc:
            err = _sanitise_exc(exc)
            return self._finalise(
                conn,
                ls_id=ls_id,
                status="failed",
                error=err,
                log=log,
                started=started,
                counts=(0, 0, 0, 0, 0, 0, 0),
            )

        # Cache points_count trên batch row để UI khỏi đếm lại. m_updated
        # không tính (rows đã thuộc batch cũ — first-writer-wins ở
        # _QUARANTINE_UPSERT_SQL). Sync 0 row mới vẫn để batch row tồn tại
        # với count=0 → "Lịch sử upload" log đầy đủ mỗi lần click.
        # Live session: reuse batch → cộng dồn delta (mỗi sync chu kỳ append
        # m_inserted rows mới vào cùng batch); sync 1 lần dùng set thường.
        if batch_id is not None:
            if reuse_batch_id is not None:
                add_batch_points_count(conn, batch_id=batch_id, delta=m_inserted)
            else:
                set_batch_points_count(conn, batch_id=batch_id, count=m_inserted)

        return self._finalise(
            conn,
            ls_id=ls_id,
            status="active",
            error=None,
            log=log,
            started=started,
            counts=(
                gw_inserted,
                gw_updated,
                gw_quarantined,
                m_inserted,
                m_updated,
                dev_inserted,
                dev_updated,
            ),
        )

    def _decrypt(self, blob: bytes) -> dict[str, str]:
        return self._cipher.decrypt(blob)

    def _finalise(
        self,
        conn: Connection,
        *,
        ls_id: UUID,
        status: str,
        error: str | None,
        log: Any,
        started: float,
        counts: tuple[int, int, int, int, int, int, int],
    ) -> SyncResult:
        now = datetime.now(UTC)
        gw_ins, gw_upd, gw_q, m_ins, m_upd, dev_ins, dev_upd = counts
        conn.execute(
            _UPDATE_SYNC_META,
            {
                "id": ls_id,
                "status": status,
                "last_sync_at": now,
                "last_sync_error": error,
            },
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        if error is None:
            log.info(
                "source_sync_completed",
                gateways_inserted=gw_ins,
                gateways_updated=gw_upd,
                gateways_quarantined=gw_q,
                measurements_inserted=m_ins,
                measurements_updated=m_upd,
                devices_inserted=dev_ins,
                devices_updated=dev_upd,
                duration_ms=duration_ms,
            )
        else:
            # error_class = constant prefix trước ":"; message phía sau đã sanitise
            log.warning(
                "source_sync_failed",
                error_class=error.split(":", 1)[0],
                duration_ms=duration_ms,
            )
        return SyncResult(
            linked_source_id=ls_id,
            gateways_inserted=gw_ins,
            gateways_updated=gw_upd,
            gateways_quarantined=gw_q,
            measurements_inserted=m_ins,
            measurements_updated=m_upd,
            devices_inserted=dev_ins,
            devices_updated=dev_upd,
            last_sync_at=now,
            error=error,
        )


# ── Helpers (private — không phải method để giữ class slim) ─────────────


def _ingest_gateways(
    conn: Connection,
    adapter: Any,
    handle: Any,
    *,
    source_type: str,
    user_id: UUID,
    ls_id: UUID,
) -> tuple[int, int, int, dict[str, UUID], dict[str, tuple[float, float]]]:
    """Split flow (mig 0029):

    * Gateway EUI đã có trong geo.gateways VÀ cùng contributor (hoặc legacy
      NULL) → upsert geo.gateways path cũ. gw_uuid lấy từ RETURNING.
    * Gateway EUI đã có nhưng khác contributor → KHÔNG cướp. Vẫn map
      gw_uuid để measurement của user này có FK serving_gateway đúng
      (gateway hardware đã approve sẵn, chỉ tên/vị trí thuộc owner gốc).
    * Gateway EUI mới hoàn toàn → quarantine path. gw_uuid_by_external
      KHÔNG ghi (FK measurement = None); coords vẫn ghi để distance filter
      hoạt động — tránh ingest measurement xa >MAX_GATEWAY_DISTANCE_KM kể
      cả khi gateway chưa duyệt.
    """
    inserted = updated = quarantined = 0
    uuid_by_external: dict[str, UUID] = {}
    coords_by_external: dict[str, tuple[float, float]] = {}
    for rec in adapter.fetch_gateways(handle):
        if not isinstance(rec, GatewayRecord):  # defensive
            continue
        existing = lookup_existing_gateway(conn, code=rec.external_id)
        if existing is None:
            # New EUI → quarantine
            _, _q_id, _review_status = upsert_gateway_quarantine(
                conn,
                rec,
                source_type=source_type,
                contributor_user_id=user_id,
                linked_source_id=ls_id,
            )
            quarantined += 1
            coords_by_external[rec.external_id] = (rec.latitude, rec.longitude)
            continue

        existing_id, existing_contributor = existing
        same_owner = existing_contributor is None or existing_contributor == user_id
        if same_owner:
            status, gw_uuid = upsert_gateway(
                conn,
                rec,
                source_type=source_type,
                contributor_user_id=user_id,
                linked_source_id=ls_id,
            )
            if status == "inserted":
                inserted += 1
            else:
                updated += 1
            uuid_by_external[rec.external_id] = gw_uuid
        else:
            # Khác owner: KHÔNG upsert (SQL cũng sẽ chặn metadata change).
            # Chỉ map gw_uuid để measurement vẫn có FK hợp lệ.
            uuid_by_external[rec.external_id] = existing_id
        coords_by_external[rec.external_id] = (rec.latitude, rec.longitude)
    return inserted, updated, quarantined, uuid_by_external, coords_by_external


def _ingest_devices(
    conn: Connection,
    adapter: Any,
    handle: Any,
    *,
    source_type: str,
    user_id: UUID,
    ls_id: UUID,
) -> tuple[int, int]:
    """Stream devices từ adapter → upsert geo.devices. Provider không hỗ trợ
    (lpwanmapper) trả iter(()) → (0, 0). Best-effort: 1 record xấu defensive
    skip; SourceError ở pagination → propagate cho caller fail toàn sync."""
    inserted = updated = 0
    for rec in adapter.fetch_devices(handle):
        if not isinstance(rec, DeviceRecord):  # defensive
            continue
        status = upsert_device(
            conn,
            rec,
            source_type=source_type,
            linked_source_id=ls_id,
            contributor_user_id=user_id,
        )
        if status == "inserted":
            inserted += 1
        else:
            updated += 1
    return inserted, updated


def _ingest_measurements(
    conn: Connection,
    adapter: Any,
    handle: Any,
    *,
    source_type: str,
    user_id: UUID,
    ls_id: UUID,
    since: datetime | None,
    gw_uuid_by_external: dict[str, UUID],
    gw_coords_by_external: dict[str, tuple[float, float]],
    batch_id: UUID | None,
    log: Any,
) -> tuple[int, int]:
    """Filter GPS-invalid records (bbox + serving-gw distance) trước upsert.
    Skip log batch-aggregate; record-level chi tiết quá ồn cho sync chu kỳ.
    """
    inserted = updated = 0
    skipped_bbox = skipped_distance = 0
    for rec in adapter.fetch_measurements(handle, since=since):
        if not is_in_vietnam(rec.latitude, rec.longitude):
            skipped_bbox += 1
            continue

        gw_uuid = (
            gw_uuid_by_external.get(rec.serving_gateway_external_id)
            if rec.serving_gateway_external_id
            else None
        )
        # Distance check chỉ khi resolve được gw coords (sync vừa upsert ở
        # bước trước → luôn có). Gateway external_id không match → gw_uuid
        # = None, skip distance check (đã không gắn FK serving_gateway).
        gw_coords = (
            gw_coords_by_external.get(rec.serving_gateway_external_id)
            if rec.serving_gateway_external_id
            else None
        )
        if gw_coords is not None:
            dist_km = haversine_km(rec.latitude, rec.longitude, gw_coords[0], gw_coords[1])
            if dist_km > MAX_GATEWAY_DISTANCE_KM:
                skipped_distance += 1
                continue

        status = upsert_measurement(
            conn,
            rec,
            source_type=source_type,
            serving_gateway_id=gw_uuid,
            serving_gateway_eui=rec.serving_gateway_external_id,
            uploader_id=user_id,
            contributor_user_id=user_id,
            linked_source_id=ls_id,
            submitted_for_community=False,
            batch_id=batch_id,
        )
        if status == "inserted":
            inserted += 1
        else:
            updated += 1

    if skipped_bbox or skipped_distance:
        log.info(
            "sync_measurements_gps_skipped",
            skipped_bbox=skipped_bbox,
            skipped_distance=skipped_distance,
            max_distance_km=MAX_GATEWAY_DISTANCE_KM,
        )

    return inserted, updated


__all__ = ["SyncReport", "SyncResult", "SyncService"]
