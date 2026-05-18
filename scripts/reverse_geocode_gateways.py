"""One-off: reverse-geocode gateway coords via Nominatim."""

from __future__ import annotations

import time
import urllib.parse
import urllib.request

GATEWAYS = [
    ("24e124fffef4778e", "24e124fffef4778e", 20.89967088823762, 106.63570404052736),
    ("7076ff0054070418", "7076ff0054070418", 20.90107409448514, 106.59278869628908),
    ("7276ff002e0507da", "DNIIT GW 0507da", 16.0740935, 108.1524913),
    ("7276ff002e06029f", "DNIIT GW 06029f", 16.0659959, 108.1532551),
    ("7276ff002e061f5b", "DNIIT GW 061f5b", 16.075590133666992, 108.22207641601562),
    ("7276ff002e062cf2", "DNIIT GW 062cf2", 16.11829376220703, 108.27363586425781),
    ("a840411eebb44150", "DNIIT GW b44150", 16.0740984, 108.15253),
    ("a84041ffff1ec39f", "DNIIT GW 1ec39f", 16.0741086, 108.1525171),
    ("ac1f09fffe00ab20", "DNIIT GW 00ab20", 16.05469, 108.22009),
    ("ac1f09fffe00ab25", "DNIIT GW 00ab25", 16.11073, 108.12857),
    ("ac1f09fffe06fcf2", "DNIIT GW 06fcf2", 16.054765682623003, 108.21985626414313),
    ("ac1f09fffe0fd629", "DNIIT GW 0fd629", 16.06815, 108.15448),
    ("ac1f09fffe0fd63b", "DNIIT GW 0fd63b", 15.98571, 108.23986),
]


def reverse(lat: float, lon: float) -> str:
    params = urllib.parse.urlencode(
        {"lat": lat, "lon": lon, "format": "json", "zoom": 18, "accept-language": "vi"}
    )
    req = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/reverse?{params}",
        headers={"User-Agent": "lora-coverage-dev/1.0 (anngh2004@gmail.com)"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        import json

        data = json.loads(resp.read())
    return data.get("display_name", "(no address)")


for code, name, lat, lon in GATEWAYS:
    addr = reverse(lat, lon)
    print(f"{code} | {name} | {lat:.6f}, {lon:.6f} | {addr}")
    time.sleep(1.1)  # Nominatim policy: max 1 req/sec
