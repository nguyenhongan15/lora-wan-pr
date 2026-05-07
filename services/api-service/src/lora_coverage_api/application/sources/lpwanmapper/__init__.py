"""lpwanmapper.com adapter (first DataSource impl).

Plan-auth-v1 §3.2. Side effect import: register LpwanmapperSource vào
sources registry với key "lpwanmapper". Caller chỉ cần
`from lora_coverage_api.application.sources import lpwanmapper`.
"""

from ..registry import register
from .adapter import LpwanmapperSource

register("lpwanmapper", LpwanmapperSource)

__all__ = ["LpwanmapperSource"]
