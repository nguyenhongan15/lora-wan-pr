"""HTTP client cho ChirpStack v4 REST API (private — chỉ adapter dùng).

API doc: https://www.chirpstack.io/docs/chirpstack/api/api.html
REST gateway endpoints generated từ gRPC; auth via Bearer API key.

Quyết định:
  * Probe endpoint = GET /api/tenants?limit=1. Hoạt động với cả global key
    (list all tenants) và tenant-scoped key (list tenant of token).
    Alternative /api/internal/profile yêu cầu JWT người dùng — không hợp
    cho API key.
  * List gateways = GET /api/gateways?limit=N&offset=M[&tenantId=X].
  * Map raw httpx error → SourceError subclasses; KHÔNG leak ra ngoài.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..errors import SourceAuthError, SourceFetchError, SourceUnreachableError

DEFAULT_TIMEOUT_S = 30.0


class Client:
    def __init__(self, base_url: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s)

    def close(self) -> None:
        self._http.close()

    def probe(self, token: str) -> None:
        """GET /api/tenants?limit=1 — validate Bearer token.

        Raises:
            SourceAuthError: 401/403 (token sai/hết hạn/không đủ quyền)
            SourceUnreachableError: network/timeout/5xx
            SourceFetchError: response status khác lạ
        """
        try:
            resp = self._http.get(
                "/api/tenants",
                headers=_auth(token),
                params={"limit": 1},
            )
        except httpx.RequestError as e:
            raise SourceUnreachableError(f"probe network error: {e}") from e

        if resp.status_code in (401, 403):
            raise SourceAuthError(f"chirpstack rejected token ({resp.status_code})")
        if resp.status_code >= 500:
            raise SourceUnreachableError(f"chirpstack upstream {resp.status_code}")
        if resp.status_code != 200:
            raise SourceFetchError(f"probe unexpected {resp.status_code}: {resp.text[:200]}")

    def list_gateways(
        self,
        *,
        token: str,
        tenant_id: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        """GET /api/gateways → {result: [...], totalCount: int}.

        Raises: same shape as probe(); 401 → SourceAuthError.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if tenant_id:
            params["tenantId"] = tenant_id
        try:
            resp = self._http.get(
                "/api/gateways",
                headers=_auth(token),
                params=params,
            )
        except httpx.RequestError as e:
            raise SourceUnreachableError(f"/api/gateways network error: {e}") from e

        if resp.status_code in (401, 403):
            raise SourceAuthError(f"chirpstack rejected token ({resp.status_code})")
        if resp.status_code >= 500:
            raise SourceUnreachableError(f"chirpstack upstream {resp.status_code}")
        if resp.status_code != 200:
            raise SourceFetchError(
                f"/api/gateways unexpected {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except ValueError as e:
            raise SourceFetchError(f"/api/gateways non-JSON: {e}") from e
        if not isinstance(data, dict):
            raise SourceFetchError(f"/api/gateways expected object, got {type(data).__name__}")
        return data


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}
