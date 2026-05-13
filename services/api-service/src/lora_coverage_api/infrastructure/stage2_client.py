"""HTTP client tới ml-service-predict POST /residual.

What:
  Stage2Client.predict_residual(target, gateway) → (residual_db, model_version) | None.
Hidden:
  httpx async client, bearer token header, payload shape, timeout fallback.
Failure mode:
  Timeout / network error / 5xx → log warning + return None (caller fallback Stage1).
  4xx (auth sai, payload sai) → cũng return None nhưng log ERROR (config bug).

Stateless theo 12F VI: httpx.AsyncClient reused trong process lifetime
(constructor inject từ deps.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from ..domain.coverage import Gateway, Target

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Stage2Result:
    """Output từ Stage 2 service. None khi service unreachable hoặc no active model."""

    residual_db: float
    model_version: str


class Stage2Client:
    """Wrap httpx.AsyncClient — 1 instance/process."""

    def __init__(
        self,
        base_url: str,
        bearer_token: str,
        client: httpx.AsyncClient,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = bearer_token
        self._client = client

    async def predict_residual(self, target: Target, gateway: Gateway) -> Stage2Result | None:
        """1 (target, serving_gateway) → residual_db + model_version.

        Return None khi:
          - 503: ml-service-predict chưa có active model.
          - Timeout / network error.
          - Auth fail.
        """
        url = f"{self._base_url}/residual"
        payload = {
            "target": {
                "latitude": target.latitude,
                "longitude": target.longitude,
                "spreading_factor": target.spreading_factor,
                "frequency_mhz": target.frequency_mhz,
            },
            "serving_gateway": {
                "id": str(gateway.id),
                "code": gateway.code,
                "name": gateway.name,
                "latitude": gateway.latitude,
                "longitude": gateway.longitude,
                "altitude_m": gateway.altitude_m,
                "antenna_height_m": gateway.antenna_height_m,
                "antenna_gain_dbi": gateway.antenna_gain_dbi,
                "tx_power_dbm": gateway.tx_power_dbm,
                "frequency_mhz": gateway.frequency_mhz,
            },
        }
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            resp = await self._client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException:
            log.warning("Stage 2 timeout (url=%s) — falling back to Stage1", url)
            return None
        except httpx.HTTPError as exc:
            log.warning("Stage 2 HTTP error: %s — falling back to Stage1", exc)
            return None

        if resp.status_code == 503:
            # No active Stage 2 model → expected during bootstrap.
            return None
        if resp.status_code == 401:
            log.error("Stage 2 auth failed (401) — check LORA_STAGE2_AUTH_TOKEN parity")
            return None
        if resp.status_code >= 400:
            log.warning("Stage 2 non-OK status %s: %s", resp.status_code, resp.text[:200])
            return None

        data = resp.json()
        return Stage2Result(
            residual_db=float(data["residual_db"]),
            model_version=str(data["model_version"]),
        )
