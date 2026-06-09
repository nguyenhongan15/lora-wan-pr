"""One-shot probe: query ChirpStack ListGateways và in last_seen_at + state.

Chạy trong container api-service (có sẵn config + decrypt):
  docker exec lora-wan-api python /app/scripts/probe_chirpstack_gateway_state.py

Output: bảng [code | name | last_seen_at | state] cho mọi gw của ChirpStack
source đã link (lấy linked source đầu tiên có source_type='chirpstack').
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from lora_coverage_api.application.linking._crypto import CredentialCipher
from lora_coverage_api.application.sources.chirpstack._client import Client
from lora_coverage_api.config import get_settings
from sqlalchemy import create_engine, text


def main() -> int:
    settings = get_settings()
    eng = create_engine(settings.database_url, pool_pre_ping=True)
    cipher = CredentialCipher(keys=settings.linking_fernet_keys_list)

    with eng.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, label, credentials_encrypted "
                "FROM auth.linked_sources "
                "WHERE source_type = 'chirpstack' "
                "ORDER BY created_at LIMIT 1"
            )
        ).first()
    if row is None:
        print("Không có linked source chirpstack nào — link 1 source trước đã.")
        return 1

    creds = cipher.decrypt(bytes(row.credentials_encrypted))
    api_url = creds["api_url"]
    api_token = creds["api_token"]
    tenant_id = creds.get("tenant_id")
    print(f"Source label={row.label!r} url={api_url} tenant_id={tenant_id}")

    client = Client(base_url=api_url.rstrip("/"), verify=False)
    try:
        offset = 0
        limit = 100
        all_items = []
        while True:
            resp = client.list_gateways(
                token=api_token, tenant_id=tenant_id, limit=limit, offset=offset
            )
            all_items.extend(resp.result)
            if len(resp.result) < limit:
                break
            offset += limit
    finally:
        client.close()

    state_label = {0: "NEVER_SEEN", 1: "ONLINE", 2: "OFFLINE"}
    now = datetime.now(UTC)
    print(f"\nTotal gateways: {len(all_items)}")
    print(f"{'code':<20} {'state':<12} {'last_seen_at (UTC)':<28} delta")
    for it in all_items:
        ls = it.last_seen_at
        if ls.seconds == 0 and ls.nanos == 0:
            ts_str = "(never)"
            delta_str = "—"
        else:
            ts = datetime.fromtimestamp(ls.seconds + ls.nanos / 1e9, tz=UTC)
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
            delta_s = (now - ts).total_seconds()
            if delta_s < 60:
                delta_str = f"{delta_s:.0f}s ago"
            elif delta_s < 3600:
                delta_str = f"{delta_s / 60:.0f}m ago"
            elif delta_s < 86400:
                delta_str = f"{delta_s / 3600:.1f}h ago"
            else:
                delta_str = f"{delta_s / 86400:.1f}d ago"
        state_name = state_label.get(it.state, f"?{it.state}")
        print(f"{it.gateway_id:<20} {state_name:<12} {ts_str:<28} {delta_str}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
