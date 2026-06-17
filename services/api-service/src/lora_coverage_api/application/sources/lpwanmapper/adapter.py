"""LpwanmapperSource — DataSource impl cho api.lpwanmapper.com.

Plan-auth-v1 §3.2. Caller chỉ thấy DataSource interface; adapter ẩn:
  * /login → cache token + gateways
  * Auto re-login khi token expire (401)
  * Best-effort field mapping (xem _mapping.py)

Credentials shape: {"email": str, "password": str}.

Quyết §14#7 (lưu password vs token): lưu password (mã hoá ở linking layer).
Token TTL không doc → adapter re-login khi 401 thay vì track expiry.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any

from ..base import (
    ConnectionHandle,
    DataSource,
    DeviceRecord,
    GatewayRecord,
    MeasurementRecord,
)
from ..errors import SourceAuthError
from . import _client, _mapping

# Bao nhiêu uplink pull mỗi lần khi caller KHÔNG truyền `limit` (= SyncService
# "Tải dữ liệu mới nhất"). API /data có param `limit` (max chưa doc, không có
# pagination/offset / since). 100k = ceiling đủ cho dataset hiện tại (~12k
# điểm) + headroom; nếu server cap thực ở 10k thì kết quả vẫn 10k — ta không
# biết tới khi probe thử. Tăng kèm timeout ở _client.py để tránh payload lớn
# time out.
_FETCH_LIMIT_SYNC = 100_000


class LpwanmapperSource(DataSource):
    def connect(self, credentials: Mapping[str, Any]) -> ConnectionHandle:
        email = credentials.get("email")
        password = credentials.get("password")
        if not email or not password:
            raise SourceAuthError("missing email/password")

        client = _client.Client()
        login = client.login(str(email), str(password))
        return {
            "client": client,
            "credentials": {"email": email, "password": password},
            "token": login["token"],
            "gateways_raw": login.get("gateways") or [],
        }

    def canonicalize_credentials(self, credentials: Mapping[str, Any]) -> Mapping[str, str]:
        # Email LÀ identity tài khoản lpwanmapper. Password thay đổi được
        # (user reset pass) → KHÔNG đưa vào fingerprint, nếu không link cùng
        # email với password mới sẽ lách UNIQUE.
        email = str(credentials.get("email") or "").strip().lower()
        if not email:
            raise SourceAuthError("missing email for fingerprint")
        return {"email": email}

    def fetch_gateways(self, handle: ConnectionHandle) -> Iterator[GatewayRecord]:
        for raw in handle["gateways_raw"]:
            rec = _mapping.gateway_record(raw)
            if rec is not None:
                yield rec

    def fetch_measurements(
        self,
        handle: ConnectionHandle,
        since: datetime | None,
        *,
        limit: int | None = None,
    ) -> Iterator[MeasurementRecord]:
        # 1 lpwanmapper /data record = 1 ChirpStack uplink → N MeasurementRecord
        # (1 / rxInfo gateway). Filter `since` áp dụng theo time của từng record
        # (API /data không hỗ trợ `since` native, phải client-side).
        effective_limit = limit if limit is not None else _FETCH_LIMIT_SYNC
        for uplink in self._fetch_data_with_reauth(handle, effective_limit):
            for rec in _mapping.measurement_records(uplink):
                if since is None or rec.time > since:
                    yield rec

    def fetch_devices(self, handle: ConnectionHandle) -> Iterator[DeviceRecord]:
        # lpwanmapper /login + /data không expose device registry — chỉ
        # uplink records có devEui inline. SyncService không upsert
        # geo.devices cho source này. (Mở rộng tương lai: derive distinct
        # devEui từ /data, nhưng metadata name/last_seen sẽ thiếu.)
        del handle
        return iter(())

    def _fetch_data_with_reauth(self, handle: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        client: _client.Client = handle["client"]
        try:
            return client.get_recent_data(handle["token"], limit=limit)
        except _client._AuthExpiredError:
            creds = handle["credentials"]
            login = client.login(creds["email"], creds["password"])
            handle["token"] = login["token"]
            return client.get_recent_data(handle["token"], limit=limit)
