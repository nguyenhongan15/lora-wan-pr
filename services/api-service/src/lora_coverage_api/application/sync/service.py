"""Sync orchestrator — pull data từ external source vào DB.

Plan-auth-v1 §3.4 + §10. Deep module: 2 method công khai (sync, sync_all_eligible)
ẩn decrypt, adapter dispatch, gateway external_id → uuid map, dedup loop, status
update, audit log.

KHÔNG raise (plan §8.3): mọi failure → SyncResult.error. Caller (edge) chỉ
inspect `result.error is None` thay vì try/except. Riêng `LinkedSourceNotFoundError`
vẫn raise để edge map → 404 (route không tồn tại ≠ sync fail).

Cross-module (plan §2):
  * Sync KHÔNG gọi LinkingService. Cipher inject như primitive (DI từ edge).
  * Co-ownership cột linked_sources:
      - Sync owns: status, last_sync_at, last_sync_error
      - Linking owns: credentials_encrypted, label, contribute_to_community,
        contributed_at, source_type, user_id
    Schema change phải đụng cả 2 module — chấp nhận leakage hợp lý cho v1
    (plan §3.4 explicitly authorizes).

Concurrency (plan §10): same linked_source bị sync đồng thời → SELECT FOR UPDATE
SKIP LOCKED ở đầu sync(). Locked → SyncResult(error="sync_in_progress"), không
raise, không UPDATE status (giữ nguyên trạng thái ổn định).
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
from ..trust import (
    TrustValidator,
    UnknownContributorError,
    promote_pending_for_linked_source,
)
from ._upsert import upsert_device, upsert_gateway, upsert_measurement

logger = structlog.get_logger("lora_coverage_api.sync")


@dataclass(frozen=True)
class SyncResult:
    """Per-source result. `error is None` ↔ success."""

    linked_source_id: UUID
    gateways_inserted: int
    gateways_updated: int
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
           credentials_encrypted, status, last_sync_at,
           contribute_to_community
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

# Eligibility filter (plan §3.4): chỉ sync source đang active + đã opt-in
# contribute + owner không bị disabled. JOIN users để áp disabled filter ở
# DB, tránh fetch row rồi loại ở Python.
_SELECT_ELIGIBLE_IDS = text("""
    SELECT ls.id, ls.user_id
    FROM auth.linked_sources ls
    JOIN auth.users u ON u.id = ls.user_id
    WHERE ls.status = 'active'
      AND ls.contribute_to_community = true
      AND u.disabled = false
    ORDER BY ls.last_sync_at NULLS FIRST, ls.created_at ASC
""")


# ── Public service ───────────────────────────────────────────────────────


class SyncService:
    """Stateless modulo (cipher, trust). Caller (edge/deps) khởi 1 instance / process.

    `trust` (TrustValidator) inject để promote pending rows sau mỗi batch
    measurement insert — plan community-data-contribution: sync ghi thẳng
    quarantine với cờ submitted_for_community, sau đó trust pipeline copy
    sang training nếu pass.
    """

    def __init__(self, *, cipher: CredentialCipher, trust: TrustValidator) -> None:
        self._cipher = cipher
        self._trust = trust

    # ── single-source ────────────────────────────────────────────────────

    def sync(
        self,
        conn: Connection,
        *,
        user: User,
        linked_source_id: UUID,
    ) -> SyncResult:
        """Pull 1 source. KHÔNG raise (trừ LinkedSourceNotFoundError → 404).

        Status update + audit log được commit cùng transaction của caller —
        caller dùng `engine.begin()` đảm bảo atomic.
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
                devices_inserted=0,
                devices_updated=0,
                measurements_inserted=0,
                measurements_updated=0,
                last_sync_at=None,
                error=_LOCKED_ERR_TAG,
            )

        return self._run_locked(conn, user_id=user.id, row=row)

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

    def _run_locked(self, conn: Connection, *, user_id: UUID, row: Any) -> SyncResult:
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
                counts=(0, 0, 0, 0, 0, 0),
            )

        # Plan community-data-contribution §3.4: measurement LUÔN ghi
        # quarantine. Cờ `submitted_for_community` đẩy theo
        # `linked_sources.contribute_to_community` — sau ingest, nếu cờ
        # bật, trust pipeline (promote_pending_for_linked_source) chạy
        # validate per-row → copy sang training nếu pass.
        contribute = bool(row.contribute_to_community)

        try:
            adapter = get_adapter(source_type)
            handle = adapter.connect(creds)
            (
                gw_inserted,
                gw_updated,
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
                submitted_for_community=contribute,
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
                counts=(0, 0, 0, 0, 0, 0),
            )

        # Promote pending → training nếu user đã opt-in cộng đồng. Best-
        # effort: validator failure (user mất khỏi auth.users giữa lúc)
        # log + skip, sync vẫn coi như success vì raw data đã ghi quarantine.
        if contribute:
            self._promote_after_sync(conn, user_id=user_id, ls_id=ls_id, log=log)

        return self._finalise(
            conn,
            ls_id=ls_id,
            status="active",
            error=None,
            log=log,
            started=started,
            counts=(gw_inserted, gw_updated, m_inserted, m_updated, dev_inserted, dev_updated),
        )

    def _promote_after_sync(
        self,
        conn: Connection,
        *,
        user_id: UUID,
        ls_id: UUID,
        log: Any,
    ) -> None:
        """Load contributor + chạy promote loop cho ls_id.

        Catch UnknownContributorError defensive — user bị xoá giữa lúc sync.
        KHÔNG raise: sync hợp lệ đã hoàn tất, promotion fail chỉ log warning.
        """
        try:
            contributor = self._trust.load_contributor(conn, user_id)
        except UnknownContributorError:
            log.warning("trust_promotion_skipped_unknown_user")
            return
        promote_pending_for_linked_source(
            conn,
            self._trust,
            contributor,
            linked_source_id=ls_id,
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
        counts: tuple[int, int, int, int, int, int],
    ) -> SyncResult:
        now = datetime.now(UTC)
        gw_ins, gw_upd, m_ins, m_upd, dev_ins, dev_upd = counts
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
) -> tuple[int, int, dict[str, UUID], dict[str, tuple[float, float]]]:
    inserted = updated = 0
    uuid_by_external: dict[str, UUID] = {}
    coords_by_external: dict[str, tuple[float, float]] = {}
    for rec in adapter.fetch_gateways(handle):
        if not isinstance(rec, GatewayRecord):  # defensive
            continue
        status, gw_uuid = upsert_gateway(
            conn,
            rec,
            source_type=source_type,
            contributor_user_id=user_id,
            linked_source_id=ls_id,
        )
        uuid_by_external[rec.external_id] = gw_uuid
        coords_by_external[rec.external_id] = (rec.latitude, rec.longitude)
        if status == "inserted":
            inserted += 1
        else:
            updated += 1
    return inserted, updated, uuid_by_external, coords_by_external


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
    submitted_for_community: bool,
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
            uploader_id=user_id,
            contributor_user_id=user_id,
            linked_source_id=ls_id,
            submitted_for_community=submitted_for_community,
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
