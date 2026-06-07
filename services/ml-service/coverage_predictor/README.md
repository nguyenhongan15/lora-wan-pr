# LoRaWAN Coverage Predictor

This module provides a lightweight inference engine for predicting the expected LoRaWAN received signal strength (RSSI) at any geographic location.

It is designed to be used by the frontend to generate network coverage maps by repeatedly evaluating:

```python
predict(lat, lon)
```

The prediction pipeline is completely independent from the model training code.

---

# Project structure

```text
coverage_predictor/
│
├── predictor.py
├── feature_builder.py
├── neighbor_features.py
├── terrain.py
│
├── data/
│   ├── gateways.csv
│   ├── reference_points.csv
│   └── terrain/
│       ├── dem.tif
│       ├── dem2.tif
│       ├── landuse.geojson
│       └── landuse2.geojson
│
└── model/
    └── extra_trees_model.pkl
```

---

# Public API

The frontend only needs to import the predictor and call:

```python
from predictor import predict

rssi = predict(
    lat=16.0735,
    lon=108.1512
)
```

Optional parameters:

```python
predict(
    lat: float,
    lon: float,
    gateway: str | None = None,
    frequency: float = 922200000,
    spreading_factor: int = 7,
) -> float
```

### Parameters

| Parameter          | Description                                                            |
| ------------------ | ---------------------------------------------------------------------- |
| `lat`              | Latitude                                                               |
| `lon`              | Longitude                                                              |
| `gateway`          | Gateway ID. If omitted, the nearest gateway is automatically selected. |
| `frequency`        | LoRa frequency in Hz                                                   |
| `spreading_factor` | LoRa spreading factor                                                  |

### Return value

```python
float
```

Predicted RSSI in dBm.

Example:

```python
-108.7
```

---

# Prediction workflow

```
predict()
    │
    ▼
build_features()
    │
    ├── Gateway selection
    ├── Geometry features
    ├── Terrain features
    └── Neighbor features
    │
    ▼
Extra Trees model
    │
    ▼
Predicted RSSI
```

---

# Feature generation

## 1. Gateway selection

If no gateway is provided:

```python
predict(lat, lon)
```

the predictor automatically selects the closest gateway using a simple Haversine distance.

The gateway information is loaded from:

```
data/gateways.csv
```

This file contains one row per gateway:

| gateway | gateway_id | gw_lat | gw_lon | gw_elevation |
| ------- | ---------- | ------ | ------ | ------------ |

---

## 2. Geometry features

The following geometric features are computed:

* distance
* distance_3d
* log_distance_3d
* delta_lat
* delta_lon
* angle
* elevation_angle

Elevation values are obtained from the DEM files.

---

## 3. Terrain features

Terrain information is extracted from:

```
data/terrain/
```

### DEM files

* dem.tif
* dem2.tif

Used for:

* elevation
* slope
* roughness

### Land use polygons

* landuse.geojson
* landuse2.geojson

Used for:

* residential_ratio

### Path analysis

The terrain profile between the gateway and the prediction point is sampled every 30 meters.

The following features are computed:

* terrain_mean
* terrain_std
* terrain_min
* terrain_max
* terrain_range
* max_obstruction
* fresnel_obstruction_ratio
* min_fresnel_clearance
* mean_fresnel_clearance
* residential_ratio

---

## 4. Neighbor features

Neighbor features are computed from a fixed reference database:

```
data/reference_points.csv
```

This dataset contains the historical packet measurements used only for inference.

For each gateway, a KDTree is built once during initialization.

The nearest neighbors are then used to compute:

* rssi_closest_point
* distance_closest_point
* closest_to_gw_distance
* neighbor_rssi_mean
* neighbor_rssi_weighted_mean
* neighbor_rssi_std
* neighbor_distance_mean
* neighbor_gw_distance_mean

These features reproduce the same logic that was used during model training.

No retraining or data cleaning occurs during inference.

---

# Model

Model type:

```
Extra Trees Regressor
```

Stored in:

```
model/extra_trees_model.pkl
```

The preprocessing pipeline is embedded inside the saved model.

The feature builder only needs to construct the input dataframe with the expected columns.

---

# Initialization

Expensive operations are performed only once when the module is imported.

```python
import predictor

    load model
    load gateways.csv
    load reference_points.csv

    build gateway lookup
    build KDTrees

    load DEM rasters
    load land-use polygons
```

After initialization:

```python
predict(...)
predict(...)
predict(...)
predict(...)
```

only computes the features for the requested point and runs the model.

---

# Design philosophy

The inference engine is intentionally separated from the training pipeline.

It does **not**:

* retrain the model
* perform cross-validation
* clean the dataset
* rebuild features for the training set
* generate CSV files

It simply:

1. loads the required resources,
2. computes the features for one point,
3. predicts the RSSI,
4. returns a floating-point value.

This makes it suitable for repeated frontend calls when generating interactive LoRaWAN coverage maps over dense geographic grids.
