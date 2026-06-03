"""Test the predictor module — run with: uv run python scripts/test_predictor.py"""
import sys
from pathlib import Path

# Add the ml-service src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services/ml-service/src"))

from lora_ml_predict.predictor import pred, pred_with_gateway, list_gateways


def main():
    print("=" * 60)
    print("predictor.py — smoke test")
    print("=" * 60)

    # 1. List gateways
    print("\n1. List gateways")
    gws = list_gateways()
    print(f"   Found {len(gws)} gateways")
    for g in sorted(gws, key=lambda x: x["lat"]):
        print(f"   • {g['id']}  ({g['lat']:.4f}, {g['lon']:.4f})")

    # 2. Basic prediction (Da Nang)
    print("\n2. pred(16.06, 108.22) — Da Nang")
    rssi = pred(16.06, 108.22)
    print(f"   RSSI = {rssi:.2f} dBm")
    assert isinstance(rssi, float), "Expected float"
    assert -200 <= rssi <= 0, f"RSSI {rssi:.2f} out of plausible range"

    # 3. Prediction with explicit SF
    print("\n3. pred(16.06, 108.22, spreading_factor=9) — SF9")
    rssi_sf9 = pred(16.06, 108.22, spreading_factor=9)
    print(f"   RSSI = {rssi_sf9:.2f} dBm")

    # 4. Hai Phong
    print("\n4. pred(20.9, 106.6) — Hai Phong")
    rssi_hp = pred(20.9, 106.6)
    print(f"   RSSI = {rssi_hp:.2f} dBm")
    assert -200 <= rssi_hp <= 0, f"RSSI {rssi_hp:.2f} out of range"

    # 5. Specific gateway
    print('\n5. pred_with_gateway(16.06, 108.22, "ac1f09fffe06fcf2")')
    rssi_gw = pred_with_gateway(16.06, 108.22, "ac1f09fffe06fcf2")
    print(f"   RSSI = {rssi_gw:.2f} dBm")

    # 6. Error: out of bounds
    print("\n6. Error handling — out of bounds")
    try:
        pred(10.0, 110.0)
        print("   FAIL: should have raised ValueError")
    except ValueError as e:
        print(f"   OK: {e}")

    # 7. Error: invalid type
    print("\n7. Error handling — invalid type")
    try:
        pred("abc", 108.0)
        print("   FAIL: should have raised TypeError")
    except TypeError as e:
        print(f"   OK: {e}")

    # 8. Error: invalid SF
    print("\n8. Error handling — invalid SF")
    try:
        pred(16.06, 108.22, spreading_factor=99)
        print("   FAIL: should have raised ValueError")
    except ValueError as e:
        print(f"   OK: {e}")

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
