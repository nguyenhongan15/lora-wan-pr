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
  - verify_ssl (optional): "true"/"false" string; default "true". Set
    "false" khi server thiếu intermediate cert hoặc dùng self-signed.

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

from ..base import (
    ConnectionHandle,
    DataSource,
    DeviceRecord,
    GatewayRecord,
    MeasurementRecord,
)
from ..errors import SourceAuthError
from . import _client, _mapping

# Page size cho /api/gateways. ChirpStack default max 250/page (server-side
# enforce). Pick 100 — đủ lớn để hạn chế round-trip với fleet vài trăm gw,
# vẫn fit response time hợp lý.
_GATEWAY_PAGE_SIZE = 100
_APPLICATION_PAGE_SIZE = 100
_DEVICE_PAGE_SIZE = 250  # ChirpStack server max — minimize round-trips


class ChirpStackSource(DataSource):
    def connect(self, credentials: Mapping[str, Any]) -> ConnectionHandle:
        api_url = credentials.get("api_url")
        api_token = credentials.get("api_token")
        if not api_url or not api_token:
            raise SourceAuthError("missing api_url/api_token")

        tenant_id_raw = credentials.get("tenant_id")
        tenant_id = str(tenant_id_raw).strip() if tenant_id_raw else None

        # `verify_ssl` đi qua wire dưới dạng string vì credentials schema
        # = dict[str, str] (xem edge/schemas.LinkSourceRequest). Parse lỏng:
        # chỉ "false" (case-insensitive) tắt verify; mọi giá trị khác giữ
        # default True. Tránh accident tắt verify do typo.
        verify_raw = credentials.get("verify_ssl")
        verify = str(verify_raw).strip().lower() != "false" if verify_raw else True

        client = _client.Client(base_url=str(api_url).rstrip("/"), verify=verify)
        # Probe = đúng endpoint sẽ dùng sau khi link (xem _client.probe). Truyền
        # tenant_id để tenant-scoped key vẫn validate được (ListTenants yêu cầu
        # global admin).
        client.probe(token=str(api_token), tenant_id=tenant_id)
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
            results = list(page.result)
            if not results:
                return
            for raw in results:
                rec = _mapping.gateway_record(raw)
                if rec is not None:
                    yield rec
            offset += len(results)
            # Trả ít hơn page-size = trang cuối; tránh dùng total_count vì 1 số
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

    def fetch_devices(self, handle: ConnectionHandle) -> Iterator[DeviceRecord]:
        """Stream mọi device visible với credential này.

        Two-level pagination: list_applications → từng app list_devices.
        ChirpStack v4 không có endpoint "list all devices in tenant" — phải
        đi qua application boundary. Adapter ẩn complexity này: caller chỉ
        thấy iterator phẳng.
        """
        client: _client.Client = handle["client"]
        token: str = handle["token"]
        tenant_id: str | None = handle["tenant_id"]

        for app_id in self._iter_application_ids(client, token, tenant_id):
            offset = 0
            while True:
                page = client.list_devices(
                    token=token,
                    application_id=app_id,
                    limit=_DEVICE_PAGE_SIZE,
                    offset=offset,
                )
                results = list(page.result)
                if not results:
                    break
                for raw in results:
                    rec = _mapping.device_record(raw)
                    if rec is not None:
                        yield rec
                offset += len(results)
                if len(results) < _DEVICE_PAGE_SIZE:
                    break

    def _iter_application_ids(
        self,
        client: _client.Client,
        token: str,
        tenant_id: str | None,
    ) -> Iterator[str]:
        offset = 0
        while True:
            page = client.list_applications(
                token=token,
                tenant_id=tenant_id,
                limit=_APPLICATION_PAGE_SIZE,
                offset=offset,
            )
            results = list(page.result)
            if not results:
                return
            for raw in results:
                app_id = (raw.id or "").strip()
                if app_id:
                    yield app_id
            offset += len(results)
            if len(results) < _APPLICATION_PAGE_SIZE:
                return
