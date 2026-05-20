"""gRPC-web client cho ChirpStack v4 API (private — chỉ adapter dùng).

ChirpStack v4 KHÔNG built-in REST API. Public deployments thường chỉ expose
gRPC-web (UI dùng), không có companion `chirpstack-rest-api`. Adapter của
ta vì thế gọi trực tiếp gRPC-web qua HTTP/1.1 POST với protobuf framing
(xem `_grpc_web.GrpcWebClient`).

Service paths:
  /api.TenantService/List       — probe (auth check)
  /api.GatewayService/List      — fetch gateways
  /api.ApplicationService/List  — list applications (2-level pagination)
  /api.DeviceService/List       — fetch devices (per application)

Lý do KHÔNG giữ REST adapter cũ làm fallback: maintenance burden 2 đường
đi cho cùng provider không justified — gRPC-web hoạt động với mọi
ChirpStack v4 deployment, bao gồm cả cái có REST sidecar.
"""

from __future__ import annotations

from chirpstack_api import api

from ._grpc_web import GrpcWebClient

DEFAULT_TIMEOUT_S = 30.0


class Client:
    def __init__(
        self,
        base_url: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        verify: bool = True,
    ) -> None:
        self._grpc = GrpcWebClient(base_url=base_url, timeout_s=timeout_s, verify=verify)

    def close(self) -> None:
        self._grpc.close()

    def probe(self, token: str, *, tenant_id: str | None) -> None:
        """Validate Bearer token bằng cách gọi đúng endpoint sẽ dùng sau khi
        link.

        Tenant-scoped API key (loại phổ biến — user tạo trong "Tenant API
        Keys") KHÔNG có quyền `ListTenants` (cần global admin). Vì
        `fetch_gateways`/`fetch_devices` đều yêu cầu `tenant_id`, probe
        dùng chính `ListGateways(tenant_id, limit=1)` → vừa kiểm tra token
        vừa kiểm tra tenant_id hợp lệ trong 1 round-trip.

        Nếu user không cung cấp `tenant_id` → token bắt buộc phải là global
        admin → fallback `ListTenants(limit=1)`.
        """
        if tenant_id:
            request = api.ListGatewaysRequest(tenant_id=tenant_id, limit=1, offset=0)
            self._grpc.call(
                service="api.GatewayService",
                method="List",
                request=request,
                response_type=api.ListGatewaysResponse,
                token=token,
            )
        else:
            request = api.ListTenantsRequest(limit=1, offset=0)
            self._grpc.call(
                service="api.TenantService",
                method="List",
                request=request,
                response_type=api.ListTenantsResponse,
                token=token,
            )

    def list_gateways(
        self,
        *,
        token: str,
        tenant_id: str | None,
        limit: int,
        offset: int,
    ) -> api.ListGatewaysResponse:
        """ChirpStack v4 yêu cầu `tenant_id` cho list gateways.

        Tenant-scoped API key tự lọc — không truyền tenant_id sẽ trả empty
        hoặc lỗi tuỳ build. Caller (adapter) đảm bảo tenant_id non-empty
        cho path này.
        """
        request = api.ListGatewaysRequest(
            tenant_id=tenant_id or "",
            limit=limit,
            offset=offset,
        )
        return self._grpc.call(
            service="api.GatewayService",
            method="List",
            request=request,
            response_type=api.ListGatewaysResponse,
            token=token,
        )

    def list_applications(
        self,
        *,
        token: str,
        tenant_id: str | None,
        limit: int,
        offset: int,
    ) -> api.ListApplicationsResponse:
        """List applications trong tenant. Yêu cầu tenant_id."""
        request = api.ListApplicationsRequest(
            tenant_id=tenant_id or "",
            limit=limit,
            offset=offset,
        )
        return self._grpc.call(
            service="api.ApplicationService",
            method="List",
            request=request,
            response_type=api.ListApplicationsResponse,
            token=token,
        )

    def list_devices(
        self,
        *,
        token: str,
        application_id: str,
        limit: int,
        offset: int,
    ) -> api.ListDevicesResponse:
        """List devices của 1 application."""
        request = api.ListDevicesRequest(
            application_id=application_id,
            limit=limit,
            offset=offset,
        )
        return self._grpc.call(
            service="api.DeviceService",
            method="List",
            request=request,
            response_type=api.ListDevicesResponse,
            token=token,
        )
