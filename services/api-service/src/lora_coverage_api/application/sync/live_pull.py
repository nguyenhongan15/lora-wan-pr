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

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import structlog
from cryptography.fernet import InvalidToken
from sqlalchemy import Connection, text

from ..identity import User
from ..linking import CredentialCipher, LinkedSourceNotFoundError
from ..sources import (
    SourceAuthError,
    get_adapter,
)

logger = structlog.get_logger("lora_coverage_api.live_pull")

_LIVE_PULL_SOURCE_TYPES = {"lpwanmapper"}

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


class LivePullService:
    """Stateless modulo cipher. Caller cấp 1 instance / process từ edge/deps."""

    def __init__(self, *, cipher: CredentialCipher) -> None:
        self._cipher = cipher

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

        try:
            creds = self._cipher.decrypt(row.credentials_encrypted)
        except InvalidToken:
            logger.error(
                "live_pull_credential_decrypt_failed",
                linked_source_id=str(linked_source_id),
            )
            raise SourceAuthError("Giải mã credential thất bại") from None

        adapter = get_adapter(row.source_type)
        handle = adapter.connect(creds)

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

        points: list[LivePullPoint] = []
        for rec in adapter.fetch_measurements(handle, since):
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


__all__ = ["LivePullPoint", "LivePullService"]
