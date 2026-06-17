"""Live-pull service — pull measurements từ external source về RAM, KHÔNG ghi DB.

Phục vụ "Theo dõi trực tiếp" view-only (CoverageMap.jsx):
  * FE poll endpoint mỗi 10s; backend connect adapter + fetch_measurements
  * Map records → shape của SurveyTrainingPointResponse để FE reuse merge logic
  * KHÔNG insert vào ts.survey_training / geo.gateways / me.upload_batches —
    muốn lưu thật user click "Tải dữ liệu mới nhất" (SyncService.sync).

Gateway UUID: lookup `geo.gateways.code = external_id`. Gateway chưa approve →
null UUID; FE skip connection line cho row đó.

Errors: SourceError (auth/network) bubble lên edge → 502 problem+json. FE catch
toast + auto-stop xem.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

import structlog
from cryptography.fernet import InvalidToken
from sqlalchemy import Connection, text

from ..identity import User
from ..linking import CredentialCipher, LinkedSourceNotFoundError
from ..sources import (
    DataSource,
    SourceAuthError,
    get_adapter,
)

logger = structlog.get_logger("lora_coverage_api.live_pull")

_LIVE_PULL_SOURCE_TYPES = {"lpwanmapper"}

# Cap số uplink kéo mỗi pull khi "Theo dõi trực tiếp" bật. Upstream /data không
# hỗ trợ `since` filter → phải tải full theo `limit` rồi filter client-side.
# DATN scope: 1-10 device, ~1-10 pkt / 15s. 50 cover được ~5-10 chu kỳ poll,
# absorb được tab idle ngắn / multi-device burst. KHÁC `_FETCH_LIMIT_SYNC`
# (100k) ở adapter — sync DB "Tải dữ liệu mới nhất" vẫn dùng default 100k.
_LIVE_PULL_LIMIT = 50

_SELECT_OWNED_SOURCE = text("""
    SELECT id, source_type, credentials_encrypted, status
    FROM auth.linked_sources
    WHERE id = :id AND user_id = :user_id
""")

_LOOKUP_GATEWAY_BY_CODE = text("""
    SELECT id FROM geo.gateways WHERE code = :code
""")


@dataclass(frozen=True, slots=True)
class LivePullPoint:
    """Shape khớp SurveyTrainingPointResponse (edge/schemas.py:223)."""

    latitude: float
    longitude: float
    rssi_dbm: float
    snr_db: float
    spreading_factor: int
    serving_gateway_id: UUID | None
    device_id: str | None
    frequency_mhz: float
    timestamp: datetime
    code_rate: str | None


@dataclass(slots=True)
class _CachedHandle:
    adapter: DataSource
    handle: Any
    # sha256(credentials_encrypted) — invalidate cache khi user re-link với
    # password mới (linked_sources row được rewrite → ciphertext khác → fingerprint khác).
    fingerprint: bytes


class LivePullService:
    """Caller cấp 1 instance / process từ edge/deps.

    Token cache (`_handles`) giữ adapter handle giữa các lần FE poll, tránh
    re-login mỗi 15-20s. Adapter `_fetch_data_with_reauth` tự re-login khi
    token 401; cache miss / `SourceAuthError` khi re-login fail → drop entry.
    """

    def __init__(self, *, cipher: CredentialCipher) -> None:
        self._cipher = cipher
        self._handles: dict[UUID, _CachedHandle] = {}
        self._lock = threading.Lock()

    def pull(
        self,
        conn: Connection,
        *,
        user: User,
        linked_source_id: UUID,
        since: datetime | None,
    ) -> list[LivePullPoint]:
        """Pull measurements > since từ source.

        Raises:
            LinkedSourceNotFoundError → 404 (không tồn tại / sai owner)
            SourceError (subclass) → 502 (adapter auth/network fail)
            UnknownSourceTypeError → 400 (source_type không hỗ trợ live)
        """
        row = conn.execute(
            _SELECT_OWNED_SOURCE, {"id": linked_source_id, "user_id": user.id}
        ).one_or_none()
        if row is None:
            raise LinkedSourceNotFoundError(f"Linked source {linked_source_id} không tồn tại")

        if row.source_type not in _LIVE_PULL_SOURCE_TYPES:
            # Chỉ lpwanmapper dùng live-pull. ChirpStack push qua webhook đã
            # vào DB; live-pull duplicate vô nghĩa.
            raise SourceAuthError(f"Source type '{row.source_type}' không hỗ trợ xem live qua API")

        entry = self._acquire_handle(
            linked_source_id=linked_source_id,
            source_type=row.source_type,
            credentials_encrypted=row.credentials_encrypted,
        )

        # Cache gateway lookup per request — 1 packet thường 1-3 rxInfo, nhiều
        # uplink share gateway → tránh re-query DB.
        gw_cache: dict[str, UUID | None] = {}

        def _resolve_gw(code: str | None) -> UUID | None:
            if code is None:
                return None
            if code in gw_cache:
                return gw_cache[code]
            row_gw = conn.execute(_LOOKUP_GATEWAY_BY_CODE, {"code": code}).one_or_none()
            gw_cache[code] = row_gw.id if row_gw else None
            return gw_cache[code]

        try:
            records = list(
                entry.adapter.fetch_measurements(entry.handle, since, limit=_LIVE_PULL_LIMIT)
            )
        except SourceAuthError:
            # Re-login thất bại (vd: user đổi password trên upstream lpwanmapper).
            # Drop cache để pull kế tiếp force decrypt + connect lại với credential
            # mới nhất từ DB. Cipher value đã decrypt ở `_acquire_handle` có thể
            # cũ; nếu user vừa re-link, row.credentials_encrypted đã đổi nhưng
            # entry vẫn xài creds cũ → drop để sync lại.
            self._invalidate(linked_source_id, entry)
            raise

        points: list[LivePullPoint] = []
        for rec in records:
            # MeasurementRecord required fields: lat/lng/rssi đã non-null;
            # snr/sf/freq nullable theo schema nhưng SurveyTrainingPointResponse
            # yêu cầu non-null cho snr/sf/freq. Skip record thiếu (rare).
            if rec.snr_db is None or rec.spreading_factor is None or rec.frequency_mhz is None:
                continue
            points.append(
                LivePullPoint(
                    latitude=rec.latitude,
                    longitude=rec.longitude,
                    rssi_dbm=rec.rssi_dbm,
                    snr_db=rec.snr_db,
                    spreading_factor=rec.spreading_factor,
                    serving_gateway_id=_resolve_gw(rec.serving_gateway_external_id),
                    device_id=rec.device_external_id,
                    frequency_mhz=rec.frequency_mhz,
                    timestamp=rec.time,
                    code_rate=rec.code_rate,
                )
            )
        return points

    def _acquire_handle(
        self,
        *,
        linked_source_id: UUID,
        source_type: str,
        credentials_encrypted: bytes,
    ) -> _CachedHandle:
        """Hot path: trả cached handle nếu fingerprint khớp. Cold path:
        decrypt + adapter.connect() (= login upstream) rồi cache.
        """
        fingerprint = sha256(credentials_encrypted).digest()
        with self._lock:
            cached = self._handles.get(linked_source_id)
            if cached is not None and cached.fingerprint == fingerprint:
                return cached

        # Cold path — decrypt + login ngoài lock vì I/O chậm (upstream HTTP).
        # Concurrent races đều an toàn: cuối cùng dict chỉ giữ 1 entry; entry
        # bị overwrite sẽ GC, httpx.Client trong handle close theo finalizer.
        try:
            creds = self._cipher.decrypt(credentials_encrypted)
        except InvalidToken:
            logger.error(
                "live_pull_credential_decrypt_failed",
                linked_source_id=str(linked_source_id),
            )
            raise SourceAuthError("Giải mã credential thất bại") from None

        adapter = get_adapter(source_type)
        handle = adapter.connect(creds)
        new_entry = _CachedHandle(adapter=adapter, handle=handle, fingerprint=fingerprint)
        with self._lock:
            self._handles[linked_source_id] = new_entry
        return new_entry

    def _invalidate(self, linked_source_id: UUID, entry: _CachedHandle) -> None:
        """Drop cache entry nếu vẫn đúng entry vừa fail. Tránh xoá nhầm entry
        mới do thread khác refresh cùng lúc.
        """
        with self._lock:
            current = self._handles.get(linked_source_id)
            if current is entry:
                del self._handles[linked_source_id]


__all__ = ["LivePullPoint", "LivePullService"]
