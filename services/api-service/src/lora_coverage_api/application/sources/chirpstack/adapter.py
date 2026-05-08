"""ChirpStackSource — DataSource impl cho ChirpStack v4 REST API.

Plan-auth-v1 §3.2. Caller chỉ thấy DataSource interface; adapter ẩn:
  * Bearer-token auth (API key user tự generate trong ChirpStack UI)
  * Pagination cho /api/gateways
  * Optional tenant_id scoping
  * Mapping JSON → GatewayRecord/MeasurementRecord

Credentials shape:
  - api_url (required): base URL của ChirpStack REST, vd "https://cs.example.com:8080"
  - api_token (required): API key (Bearer)
  - tenant_id (optional): UUID — nếu set, scope query theo tenant đó

Khác lpwanmapper:
  - lpwanmapper /login trả luôn gateways trong response → 1 call.
    ChirpStack tách: list gateways riêng, paginate → fetch_gateways stream.
  - lpwanmapper /data trả bulk uplinks recent. ChirpStack v4 KHÔNG có
    endpoint dump bulk uplinks lịch sử (frame log buffer nhỏ, design cho
    streaming/webhook). v1 fetch_measurements trả empty + comment — hướng
    đi đúng cho ChirpStack là webhook integration (v2). User vẫn link +
    sync gateways được, đủ chứng minh multi-source architecture.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any

from ..base import ConnectionHandle, DataSource, GatewayRecord, MeasurementRecord
from ..errors import SourceAuthError
from . import _client, _mapping

# Page size cho /api/gateways. ChirpStack default max 250/page (server-side
# enforce). Pick 100 — đủ lớn để hạn chế round-trip với fleet vài trăm gw,
# vẫn fit response time hợp lý.
_GATEWAY_PAGE_SIZE = 100


class ChirpStackSource(DataSource):
    def connect(self, credentials: Mapping[str, Any]) -> ConnectionHandle:
        api_url = credentials.get("api_url")
        api_token = credentials.get("api_token")
        if not api_url or not api_token:
            raise SourceAuthError("missing api_url/api_token")

        tenant_id_raw = credentials.get("tenant_id")
        tenant_id = str(tenant_id_raw).strip() if tenant_id_raw else None

        client = _client.Client(base_url=str(api_url).rstrip("/"))
        # Lightweight authenticated probe — list 1 tenant. 401 → SourceAuthError,
        # khác lỗi → SourceUnreachable/Fetch theo client.
        client.probe(token=str(api_token))
        return {
            "client": client,
            "token": str(api_token),
            "tenant_id": tenant_id,
        }

    def canonicalize_credentials(self, credentials: Mapping[str, Any]) -> Mapping[str, str]:
        # api_url + api_token cùng nhau LÀ identity (cùng deployment, cùng
        # token = cùng quyền truy cập). tenant_id scope nội dung visible
        # nhưng KHÔNG thay token → đưa vào fingerprint cho phép cùng token
        # link 2 lần với tenant khác nhau (use case hợp lệ: user link tenant
        # A của họ và tenant B của họ riêng).
        api_url = str(credentials.get("api_url") or "").strip().rstrip("/").lower()
        api_token = str(credentials.get("api_token") or "").strip()
        if not api_url or not api_token:
            raise SourceAuthError("missing api_url/api_token for fingerprint")
        tenant_id = str(credentials.get("tenant_id") or "").strip()
        return {"api_url": api_url, "api_token": api_token, "tenant_id": tenant_id}

    def fetch_gateways(self, handle: ConnectionHandle) -> Iterator[GatewayRecord]:
        client: _client.Client = handle["client"]
        token: str = handle["token"]
        tenant_id: str | None = handle["tenant_id"]
        offset = 0
        while True:
            page = client.list_gateways(
                token=token,
                tenant_id=tenant_id,
                limit=_GATEWAY_PAGE_SIZE,
                offset=offset,
            )
            results = page.get("result")
            if not isinstance(results, list) or not results:
                return
            for raw in results:
                if not isinstance(raw, dict):
                    continue
                rec = _mapping.gateway_record(raw)
                if rec is not None:
                    yield rec
            offset += len(results)
            # Trả ít hơn page-size = trang cuối; tránh dùng totalCount vì 1 số
            # build trả -1 hoặc bỏ qua field này.
            if len(results) < _GATEWAY_PAGE_SIZE:
                return

    def fetch_measurements(
        self,
        handle: ConnectionHandle,
        since: datetime | None,
    ) -> Iterator[MeasurementRecord]:
        # ChirpStack v4 không expose bulk historical uplink qua REST. Frame log
        # là buffer nhỏ realtime cho UI debug, không phải data store. Cách
        # tích hợp đúng = ChirpStack HTTP integration push uplinks về
        # webhook của ta (v2). v1 trả empty: link + sync gateways vẫn hoạt
        # động, đủ validate multi-source architecture.
        del handle, since
        return iter(())
