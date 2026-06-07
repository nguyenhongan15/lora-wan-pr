coverage_predictor/

│
├── predictor.py              
├── feature_builder.py 
├── neighbor_features.py 
│
├── data/
│   ├── reference_points.csv
│   └── gateways.csv
│
└── model/
    └── extra_trees_model.pkl


Workflow :

predict(lat, lon)
        │
        ▼
select_gateway()
        │
        ▼
build_features()
        │
        ├── geometry
        ├── terrain
        └── get_neighbor_features()
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