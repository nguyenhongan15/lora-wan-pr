import pandas as pd


def parse_devices(data):
    rows = []
    for item in data:
        device = item.get("deviceInfo", {}).get("deviceName", None)
        obj = item.get("object", {})

        lat = obj.get("gnss_latitude", None)
        lon = obj.get("gnss_longitude", None)
        lat, lon = fix_gps(lat, lon)

        tx = item.get("txInfo", {})
        lora = tx.get("modulation", {}).get("lora", {})

        for rx in item.get("rxInfo", []):
            loc = rx.get("location", {})

            row = {
                "device": device,
                "lat": lat,
                "lon": lon,
                "gateway": rx.get("gatewayId"),
                "gw_lat": loc.get("latitude"),
                "gw_lon": loc.get("longitude"),
                "rssi": rx.get("rssi"),
                "snr": rx.get("snr"),
                "time": item.get("time"),
                "frequency": tx.get("frequency"),
                "bandwidth": lora.get("bandwidth"),
                "spreading_factor": lora.get("spreadingFactor"),
            }
            if row["lat"] is not None and row["lon"] is not None:
                rows.append(row)

    df = pd.DataFrame(rows)
    return df


def fix_gps(lat, lon):
    if lat is None or lon is None:
        return None, None

    while lat < -90 or lat > 90:
        lat = lat / 10
    while lon < -180 or lon > 180:
        lon = lon / 10

    if lat < 15 or lon < 102:
        print("suppression : ", lat, lon)
        return None, None

    return lat, lon
