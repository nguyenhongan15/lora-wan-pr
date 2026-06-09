"""Gateway state service — fetch ChirpStack last_seen_at + state.

Public API:
- `GatewayStateService.get_state_map()` → {gateway_code: GatewayState}
- `GatewayState` dataclass (state literal + last_seen_at)
"""

from .service import GatewayState, GatewayStateService

__all__ = ["GatewayState", "GatewayStateService"]
