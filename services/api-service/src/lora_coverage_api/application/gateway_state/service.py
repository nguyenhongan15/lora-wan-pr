"""Gateway state service — query ChirpStack ListGateways, cache map vào Valkey.

Flow:
  GET /api/v1/gateways → router gọi `get_state_map()` →
  hit cache (Valkey, key "gw_state:v1", TTL config) → trả dict {code: state}.
  Miss → SELECT auth.linked_sources WHERE source_type='chirpstack' ORDER BY
  created_at LIMIT 1 → decrypt → ChirpStack `GatewayService.List` (paginated) →
  build map → setex cache → return.

Failure mode: ChirpStack down / no linked source → trả dict rỗng (router
fallback state='unknown' cho mọi gw). KHÔNG raise — endpoint /api/v1/gateways
phải hoạt động dù ChirpStack down.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import Engine, text

from ..linking._crypto import CredentialCipher
from ..sources.chirpstack._client import Client

log = logging.getLogger(__name__)

StateLiteral = Literal["online", "offline", "never_seen", "unknown"]
_CS_STATE_MAP: dict[int, StateLiteral] = {
    0: "never_seen",
    1: "online",
    2: "offline",
}
_CACHE_KEY = "gw_state:v1"
_LIST_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class GatewayState:
    state: StateLiteral
    last_seen_at: datetime | None


class GatewayStateService:
    def __init__(
        self,
        engine: Engine,
        cipher: CredentialCipher,
        cache_url: str,
        ttl_s: int = 60,
    ) -> None:
        self._eng = engine
        self._cipher = cipher
        self._ttl_s = ttl_s
        self._cache = None
        if cache_url:
            import redis

            self._cache = redis.from_url(cache_url, decode_responses=True)  # type: ignore[no-untyped-call]

    def get_state_map(self) -> dict[str, GatewayState]:
        """Return {gateway_code: GatewayState}. Empty dict nếu fail."""
        if self._cache is not None:
            try:
                cached = self._cache.get(_CACHE_KEY)
            except Exception as exc:
                log.warning("gateway-state cache read failed: %s", exc)
                cached = None
            if isinstance(cached, str) and cached:
                return _deserialize(cached)

        state_map = self._fetch_from_chirpstack()

        if self._cache is not None and state_map:
            try:
                self._cache.setex(_CACHE_KEY, self._ttl_s, _serialize(state_map))
            except Exception as exc:
                log.warning("gateway-state cache write failed: %s", exc)

        return state_map

    def _fetch_from_chirpstack(self) -> dict[str, GatewayState]:
        with self._eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT credentials_encrypted "
                    "FROM auth.linked_sources "
                    "WHERE source_type = 'chirpstack' "
                    "ORDER BY created_at LIMIT 1"
                )
            ).first()
        if row is None:
            log.info("Không có linked source chirpstack — trả state map rỗng")
            return {}

        try:
            creds = self._cipher.decrypt(bytes(row.credentials_encrypted))
        except Exception as exc:
            log.warning("decrypt chirpstack creds fail: %s", exc)
            return {}

        api_url = creds.get("api_url", "").rstrip("/")
        api_token = creds.get("api_token", "")
        tenant_id = creds.get("tenant_id") or None
        verify_raw = creds.get("verify_ssl")
        verify = str(verify_raw).strip().lower() != "false" if verify_raw else True
        if not api_url or not api_token:
            log.warning("chirpstack creds thiếu api_url/api_token")
            return {}

        client = Client(base_url=api_url, verify=verify)
        state_map: dict[str, GatewayState] = {}
        try:
            offset = 0
            while True:
                resp = client.list_gateways(
                    token=api_token,
                    tenant_id=tenant_id,
                    limit=_LIST_PAGE_SIZE,
                    offset=offset,
                )
                for item in resp.result:
                    code = str(item.gateway_id).lower()
                    ts = item.last_seen_at
                    if ts.seconds == 0 and ts.nanos == 0:
                        last_seen = None
                    else:
                        last_seen = datetime.fromtimestamp(ts.seconds + ts.nanos / 1e9, tz=UTC)
                    state_map[code] = GatewayState(
                        state=_CS_STATE_MAP.get(item.state, "unknown"),
                        last_seen_at=last_seen,
                    )
                if len(resp.result) < _LIST_PAGE_SIZE:
                    break
                offset += _LIST_PAGE_SIZE
        except Exception as exc:
            log.warning("chirpstack list_gateways fail: %s", exc)
            return {}
        finally:
            client.close()

        return state_map


def _serialize(state_map: dict[str, GatewayState]) -> str:
    return json.dumps(
        {
            code: {
                "state": s.state,
                "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
            }
            for code, s in state_map.items()
        }
    )


def _deserialize(blob: str) -> dict[str, GatewayState]:
    raw = json.loads(blob)
    out: dict[str, GatewayState] = {}
    for code, entry in raw.items():
        ts_raw = entry.get("last_seen_at")
        ts = datetime.fromisoformat(ts_raw) if ts_raw else None
        out[str(code)] = GatewayState(state=entry["state"], last_seen_at=ts)
    return out
