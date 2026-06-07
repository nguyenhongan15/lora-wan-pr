# Wireless Coverage ML

Machine learning framework for terrain-aware wireless coverage prediction using LoRaWAN measurements and geospatial information.

---

# Overview

The objective of this project is to estimate RSSI values and generate wireless coverage maps from:

* GPS-tagged signal measurements,
* digital elevation models,
* OpenStreetMap land-use data,
* local spatial statistics extracted from historical measurements.

Unlike traditional propagation models, the proposed approach learns the relationship between terrain, radio parameters and neighboring observations directly from data.

---

# Project Structure

```text
wireless-coverage-ml/

├── data/
│   ├── raw/
│   ├── processed/
│   └── terrain/
│
├── src/
│   ├── api/
│   │   ├── client.py
│   │   └── fetch_data.py
│   │
│   ├── processing/
│   │   ├── parser.py
│   │   ├── cleaning.py
│   │   ├── terrain.py
│   │   ├── terrain_type.py
│   │   └── features.py
│   │
│   ├── ml/
│   │   ├── train.py
│   │   ├── pipeline.py
│   │   ├── predict.py
│   │   └── models/
│   │
│   ├── download_osm.py
│   └── main.py
│
├── requirements.txt
└── README.md
```

---

# Feature Engineering

## Radio Features

* Frequency
* Spreading Factor

## Geometrical Features

* 3D distance
* Log 3D distance
* Relative angle
* Latitude difference
* Longitude difference

## Terrain Features

* Elevation
* Gateway elevation
* Elevation difference
* Elevation angle
* Slope
* Roughness
* Terrain statistics

## Propagation Features

* Maximum obstruction
* Fresnel obstruction ratio
* Minimum Fresnel clearance
* Mean Fresnel clearance

## Land Use

* Residential area ratio

## Spatial Neighborhood Features

Historical measurements are indexed using a KD-tree for each gateway.

For every prediction point, the algorithm computes:

* RSSI of the closest measurement
* Distance to closest measurement
* Gateway distance of closest measurement
* Mean neighboring RSSI
* Weighted neighboring RSSI mean
* Neighbor RSSI standard deviation
* Mean neighboring distance
* Mean neighboring gateway distance

These local statistics constitute the most informative feature group of the final model.

---

# Machine Learning

The following regression families were evaluated:

* Random Forest
* Extra Trees
* XGBoost
* HistGradientBoosting
* Multi-Layer Perceptron
* Support Vector Regression

Final selected model:

| Parameter         |       Value |
| ----------------- | ----------: |
| Model             | Extra Trees |
| Trees             |         650 |
| Max Depth         |          18 |
| Max Features      |         0.7 |
| Min Samples Split |          10 |

Cross-validation performance:

| Metric |           Value |
| ------ | --------------: |
| R²     | 0.9285 ± 0.0065 |
| MAE    |        1.93 dBm |
| RMSE   |        2.92 dBm |

---

# Prediction Pipeline Goal

```text
Query Point
(lat, lon, gateway, frequency, sf)

        │

        ▼

Load:
- trained model
- KD-tree reference database
- DEM
- land-use data

        │

        ▼

Compute:
- terrain features
- propagation features
- nearest-neighbor statistics

        │

        ▼

Extra Trees prediction

        │

        ▼

Predicted RSSI
```

