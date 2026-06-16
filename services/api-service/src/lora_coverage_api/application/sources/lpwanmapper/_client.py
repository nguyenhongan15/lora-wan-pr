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

from typing import Any, cast

import httpx

from ..errors import SourceAuthError, SourceFetchError, SourceUnreachableError

DEFAULT_BASE_URL = "https://api.lpwanmapper.com"
DEFAULT_TIMEOUT_S = 180.0


class _AuthExpiredError(Exception):
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
            SourceAuthError: 400/401 (sai credential)
            SourceUnreachableError: network/timeout
            SourceFetchError: response không phải JSON object hợp lệ
        """
        try:
            resp = self._http.post("/login", json={"email": email, "password": password})
        except httpx.RequestError as e:
            raise SourceUnreachableError(f"login network error: {e}") from e

        if resp.status_code in (400, 401):
            raise SourceAuthError(f"login rejected ({resp.status_code})")
        if resp.status_code >= 500:
            raise SourceUnreachableError(f"login upstream {resp.status_code}")
        if resp.status_code != 200:
            raise SourceFetchError(f"login unexpected {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as e:
            raise SourceFetchError(f"login non-JSON response: {e}") from e
        if not isinstance(data, dict) or "token" not in data:
            raise SourceFetchError("login response missing 'token'")
        return data

    def get_recent_data(self, token: str, limit: int) -> list[dict[str, Any]]:
        """POST /data {limit} → list[record]. Raise _AuthExpiredError nếu 401."""
        try:
            resp = self._http.post(
                "/data",
                headers={"Authorization": f"Bearer {token}"},
                json={"limit": limit},
            )
        except httpx.RequestError as e:
            raise SourceUnreachableError(f"/data network error: {e}") from e

        if resp.status_code == 401:
            raise _AuthExpiredError()
        if resp.status_code >= 500:
            raise SourceUnreachableError(f"/data upstream {resp.status_code}")
        if resp.status_code != 200:
            raise SourceFetchError(f"/data unexpected {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except ValueError as e:
            raise SourceFetchError(f"/data non-JSON response: {e}") from e
        if not isinstance(data, list):
            # API có thể wrap trong {"data": [...]} — accept cả 2 dạng.
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                return cast(list[dict[str, Any]], data["data"])
            raise SourceFetchError(f"/data expected list, got {type(data).__name__}")
        return data
