"""LoRa Coverage Platform — REST API service.

5-layer architecture (enforced by import-linter):

    edge  →  application  →  domain
                ↑
        infrastructure (only edge wires it in)

Quy tắc bất biến:
  - application/ KHÔNG import infrastructure/.
  - domain/ KHÔNG import bất cứ thứ gì khác trong package này.
  - application/ KHÔNG được mention bất kỳ storage-tier identifier nào
  (xem CI grep rule trong .github/workflows/ci.yml).
"""

__version__ = "0.1.0"
