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


Workflow :

predict(lat, lon)
        │
        ▼
build_features()
        │
        ├── geometry
        ├── terrain
        └── neighbor
        │
        ▼
model.predict()
        │
        ▼
float RSSI
  
  
Everything expensive should happen only once:

import predictor

    load model
    load gateways
    load reference dataset
    build KDTrees

predict(...)
predict(...)
predict(...)
predict(...)
...