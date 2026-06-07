from joblib import load

from feature_builder import build_features

MODEL = load("model/extra_trees_model.pkl")

def predict(
    lat: float,
    lon: float,
    gateway: str | None = None,
    frequency: float | None = None,
    spreading_factor: int | None = None,
) -> float:
    """Predict the signal strength at a given location.

    Args:
        lat: Latitude of the location.
        lon: Longitude of the location.
        gateway: The gateway to use for the prediction. If None, the closest gateway will be used.
        frequency: The frequency to use for the prediction. If None, the default frequency will be used.
        spreading_factor: The spreading factor to use for the prediction. If None, the default spreading factor will be used.

    Returns:
        The predicted signal strength in dBm.
    """

    if gateway is None:
        # gateway = select_best_gateway(lat, lon)
        print("No gateway provided, using default gateway 'gateway_1'")

    if frequency is None:
        frequency = 868.1

    if spreading_factor is None:
        spreading_factor = 7

    X = build_features(
        lat=lat,
        lon=lon,
        gateway=gateway,
        frequency=frequency,
        spreading_factor=spreading_factor
    )

    return float(MODEL.predict(X)[0])