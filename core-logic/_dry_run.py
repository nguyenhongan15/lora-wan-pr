import csv
from pathlib import Path

from lora_coverage_api.domain.coverage import GatewayId, Target
from lora_coverage_api.edge.deps import _engine, trust_validator
from sqlalchemy import text

val = trust_validator()
with _engine().begin() as conn:
    row = conn.execute(text("SELECT id FROM geo.gateways WHERE code='ac1f09fffe06fcf2'")).one()
gw = val._directory.get_by_id(GatewayId(row.id))

passed = failed = 0
deltas = []
with Path("/tmp/danang_test_data_gw06fcf2_v2.csv").open() as f:
    for r in csv.DictReader(f):
        lat = float(r["latitude"])
        lon = float(r["longitude"])
        rssi = float(r["rssi_dbm"])
        sf = int(r["spreading_factor"])
        t = Target(latitude=lat, longitude=lon, spreading_factor=sf, frequency_mhz=923.0)
        try:
            pred = val._model.predict(t, gw).rssi_dbm
        except Exception:
            failed += 1
            continue
        d = abs(rssi - pred)
        deltas.append(d)
        if d <= 15:
            passed += 1
        else:
            failed += 1
print(
    f"threshold=15dB  passed={passed}  failed={failed}  "
    f"max_delta={max(deltas):.1f}  mean={sum(deltas) / len(deltas):.1f}"
)
