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

from ..base import ConnectionHandle, DataSource, GatewayRecord, MeasurementRecord
from ..errors import SourceAuthFailed
from . import _client, _mapping

# Bao nhiêu measurement pull mỗi lần. API /data có param `limit` (max chưa
# doc). Lấy 10k làm safe ceiling cho v1; nếu user có > 10k records mới sẽ
# bị truncate — chấp nhận trade-off này v1, paginate ở v2 nếu cần.
_FETCH_LIMIT = 10_000


class LpwanmapperSource(DataSource):
    def connect(self, credentials: Mapping[str, Any]) -> ConnectionHandle:
        email = credentials.get("email")
        password = credentials.get("password")
        if not email or not password:
            raise SourceAuthFailed("missing email/password")

        client = _client.Client()
        login = client.login(str(email), str(password))
        return {
            "client": client,
            "credentials": {"email": email, "password": password},
            "token": login["token"],
            "gateways_raw": login.get("gateways") or [],
        }

    def fetch_gateways(self, handle: ConnectionHandle) -> Iterator[GatewayRecord]:
        for raw in handle["gateways_raw"]:
            rec = _mapping.gateway_record(raw)
            if rec is not None:
                yield rec

    def fetch_measurements(
        self,
        handle: ConnectionHandle,
        since: datetime | None,
    ) -> Iterator[MeasurementRecord]:
        # 1 lpwanmapper /data record = 1 ChirpStack uplink → N MeasurementRecord
        # (1 / rxInfo gateway). Filter `since` áp dụng theo time của từng record.
        for uplink in self._fetch_data_with_reauth(handle):
            for rec in _mapping.measurement_records(uplink):
                if since is None or rec.time > since:
                    yield rec

    def _fetch_data_with_reauth(self, handle: dict) -> list[dict]:
        client = handle["client"]
        try:
            return client.get_recent_data(handle["token"], limit=_FETCH_LIMIT)
        except _client._AuthExpired:
            creds = handle["credentials"]
            login = client.login(creds["email"], creds["password"])
            handle["token"] = login["token"]
            return client.get_recent_data(handle["token"], limit=_FETCH_LIMIT)
