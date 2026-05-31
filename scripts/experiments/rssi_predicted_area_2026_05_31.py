"""Count area share of each RSSI bin in the predicted composite GeoJSON.

Compare with measured distribution to see whether model over/under-predicts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from shapely.geometry import shape

GEOJSON = Path("apps/web-app/public/coverage/rssi/composite.geojson")
BIN_LABEL = {
    1: ">=-100 (strong green)",
    2: "-110..-100 (good yellow)",
    3: "-120..-110 (marg orange)",
    4: "-140..-120 (weak red)",
}


def main() -> None:
    if not GEOJSON.exists():
        sys.exit(f"missing {GEOJSON}")
    data = json.loads(GEOJSON.read_text(encoding="utf-8"))
    by_bin: dict[int, float] = {}
    for feat in data["features"]:
        b = int(feat["properties"]["bin"])
        a = shape(feat["geometry"]).area  # degrees² — not real km² but fine for ratio
        by_bin[b] = by_bin.get(b, 0.0) + a
    total = sum(by_bin.values())
    print(f"{'bin':<6} {'label':<28} {'share_%':>8}")
    for b in sorted(by_bin):
        print(f"{b:<6} {BIN_LABEL[b]:<28} {100 * by_bin[b] / total:>8.2f}")
    print(f"total area (sum of 4 bins, masked sea removed): {total:.4f} deg^2")


if __name__ == "__main__":
    main()
