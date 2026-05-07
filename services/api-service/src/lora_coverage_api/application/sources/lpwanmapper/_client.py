"""HTTP client cho api.lpwanmapper.com (private — chỉ adapter dùng).

Map raw httpx error → SourceError subclasses. Không retain state ngoài base_url.

API doc: https://api.lpwanmapper.com/apidocs/

Quyết định:
  * Auth header: 'Authorization: Bearer <token>' (doc không nêu rõ; nếu API
    yêu cầu format khác thì smoke test sẽ phát hiện qua 401, sửa ở đây).
  * /login response chứa luôn `gateways` array → adapter cache, không gọi
    endpoint riêng.
  * /data dùng POST với body {limit: N} — endpoint duy nhất trả bulk
    measurements user đã ingest. Không có time filter native; caller filter
    `since` client-side.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..errors import SourceAuthFailed, SourceFetchFailed, SourceUnreachable

DEFAULT_BASE_URL = "https://api.lpwanmapper.com"
DEFAULT_TIMEOUT_S = 30.0


class _AuthExpired(Exception):
    """Internal sentinel — adapter catch và re-login. Không leak ra ngoài module."""


class Client:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s)

    def close(self) -> None:
        self._http.close()

    def login(self, email: str, password: str) -> dict[str, Any]:
        """POST /login → {token, webhook_url, deviceNames[], gateways[]}.

        Raises:
            SourceAuthFailed: 400/401 (sai credential)
            SourceUnreachable: network/timeout
            SourceFetchFailed: response không phải JSON object hợp lệ
        """
        try:
            resp = self._http.post("/login", json={"email": email, "password": password})
        except httpx.RequestError as e:
            raise SourceUnreachable(f"login network error: {e}") from e

        if resp.status_code in (400, 401):
            raise SourceAuthFailed(f"login rejected ({resp.status_code})")
        if resp.status_code >= 500:
            raise SourceUnreachable(f"login upstream {resp.status_code}")
        if resp.status_code != 200:
            raise SourceFetchFailed(f"login unexpected {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as e:
            raise SourceFetchFailed(f"login non-JSON response: {e}") from e
        if not isinstance(data, dict) or "token" not in data:
            raise SourceFetchFailed("login response missing 'token'")
        return data

    def get_recent_data(self, token: str, limit: int) -> list[dict[str, Any]]:
        """POST /data {limit} → list[record]. Raise _AuthExpired nếu 401."""
        try:
            resp = self._http.post(
                "/data",
                headers={"Authorization": f"Bearer {token}"},
                json={"limit": limit},
            )
        except httpx.RequestError as e:
            raise SourceUnreachable(f"/data network error: {e}") from e

        if resp.status_code == 401:
            raise _AuthExpired()
        if resp.status_code >= 500:
            raise SourceUnreachable(f"/data upstream {resp.status_code}")
        if resp.status_code != 200:
            raise SourceFetchFailed(f"/data unexpected {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except ValueError as e:
            raise SourceFetchFailed(f"/data non-JSON response: {e}") from e
        if not isinstance(data, list):
            # API có thể wrap trong {"data": [...]} — accept cả 2 dạng.
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                return data["data"]
            raise SourceFetchFailed(f"/data expected list, got {type(data).__name__}")
        return data
