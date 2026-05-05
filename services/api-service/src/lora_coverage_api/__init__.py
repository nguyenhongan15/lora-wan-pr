"""LoRa Coverage Platform — REST API service.

5-layer architecture (enforced by import-linter):

    edge  →  application  →  domain
                ↑
        infrastructure (only edge wires it in)

Quy tắc bất biến:
  - application/ KHÔNG import infrastructure/.
  - domain/ KHÔNG import bất cứ thứ gì khác trong package này.
  - application/ KHÔNG mention "postgres", "redis", "valkey", "s3",
    "stage_4", "GiST", "BRIN" (CI grep).
"""

__version__ = "0.1.0"
