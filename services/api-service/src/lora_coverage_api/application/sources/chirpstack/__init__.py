"""ChirpStack v4 adapter (second DataSource impl).

Plan-auth-v1 §3.2 + §11. Side effect import: register ChirpStackSource vào
sources registry với key "chirpstack". Caller chỉ cần
`from lora_coverage_api.application.sources import chirpstack`.
"""

from ..registry import register
from .adapter import ChirpStackSource

register("chirpstack", ChirpStackSource)

__all__ = ["ChirpStackSource"]
