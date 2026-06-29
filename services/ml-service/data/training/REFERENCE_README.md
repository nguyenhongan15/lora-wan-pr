# Wireless Coverage ML

Machine learning pipeline for wireless coverage prediction using API data and geospatial features.

## Project Structure

```text
wireless-coverage-ml/
│
├── data/
│   ├── terrain/          # terrain data
│   ├── raw/          # raw API data
│   └── processed/    # cleaned datasets
│
├── src/
│   ├── api/
│   │   ├── client.py
│   │   └── fetch_data.py
│   │
│   ├── processing/
│   │   ├── terrain_type.py
│   │   ├── terrain.py
│   │   ├── parser.py
│   │   ├── features.py
│   │   └── cleaning.py
│   │
│   ├── ml/
│   │   ├── models/ #model.pkl file
│   │   ├── pipeline.py
│   │   ├── predict.py
│   │   └── train.py
│   │
│   ├── download_osm.py #to get landuse data
│   └── main.py
│
├── requirements.txt
└── README.md
``` 
## Features

device                       10210
lat                          10210
lon                          10210
gateway                      10210
gw_lat                       10210
gw_lon                       10210
rssi(target)                 10210
snr                          10210
time                         10210
frequency                    10210
bandwidth                    10210
spreading_factor             10210
distance                     10210
log_distance                 10210
delta_lat                    10210
delta_lon                    10210
angle                        10210
gateway_id                   10210
elevation                    10210
gw_elevation                 10210
delta_elevation              10210
terrain_type                 10210
distance_3d                  
log_distance_3d              
fspl                         
elevation_angle              
slope                        
roughness                    
terrain_mean                 
terrain_std                  
terrain_min                  
terrain_max                  
terrain_range                
obstruction_ratio            
max_obstruction              
mean_obstruction             
fresnel_obstruction_ratio    
min_fresnel_clearance        
mean_fresnel_clearance       
forest_ratio                 
water_ratio                 
residential_ratio            
unknown_ratio                   

## Data

Elevation Map (.tiff) from OpenTopography
Dataset Citation: NASA Shuttle Radar Topography Mission (SRTM)(2013). Shuttle Radar Topography Mission (SRTM) Global. Distributed by OpenTopography. https://doi.org/10.5069/G9445JDF. Accessed 2026-05-07       

dem.tiff : bounds=(108.08, 15.87, 108.32, 16.12) Da Nang

dem2.tiff : bounds=(106.05, 20.65,106.65, 20.92 ) Hai Phong

dem1.tiff : bounds=(107.0804443527013, 15.15856441049533, 108.97888205386698, 16.70512780665861) Da Nang and around


INFOS SUPP : 
bounds=(108.08, 15.87, 108.32, 16.12) pour la carte dl sur "OpenTopography : changed to  Xmin = 107.0804443527013	  Ymin = 15.15856441049533	  Xmax = 108.97888205386698	  Ymax = 16.70512780665861

https://docs.google.com/spreadsheets/d/1hss_oUUUP1r3d4MA8pTS3w_L92m9-wUM-oP_nc6zV4I/edit?pli=1&gid=1161341563#gid=1161341563 

High-Resolution Topography Data and Tools"
Dataset Citation: NASA Shuttle Radar Topography Mission (SRTM)(2013). Shuttle Radar Topography Mission (SRTM) Global. Distributed by OpenTopography. https://doi.org/10.5069/G9445JDF. Accessed 2026-05-07       
Use License: Not Provided

bounds2=(106.05, 20.65,106.65, 20.92 )

Gateway 7276ff002e062cf2 at longitude 108.273681640625 and latitude 16.118301391601562 : delta elevation crazy -> verif gg maps : Son tra sommet montagne.

===== RESULTS ===== RANDOM FOREST
MAE  : 2.15 dBm
RMSE : 3.77 dBm
R²   : 0.8872
features importance avec random forest : 
                          feature    importance
17                num__terrain_max  2.637750e-01
12                      num__slope  1.877622e-01
9             num__delta_elevation  6.890332e-02
16                num__terrain_min  6.505000e-02
10            num__elevation_angle  6.306178e-02
30   cat__gateway_7076ff0054070418  4.933417e-02
29   cat__gateway_24e124fffef4778e  4.492214e-02
33   cat__gateway_7276ff002e061f5b  2.529312e-02Local\src> 
0                   num__frequency  2.492653e-02
6             num__log_distance_3d  2.051328e-02
24     num__mean_fresnel_clearance  1.960808e-02
4                num__log_distance  1.846207e-02
3                    num__distance  1.818727e-02
5                 num__distance_3d  1.789327e-02
11                       num__fspl  1.772674e-02
8                num__gw_elevation  1.274121e-02
14               num__terrain_mean  1.007954e-02
15                num__terrain_std  9.766615e-03
23      num__min_fresnel_clearance  8.763362e-03
13                  num__roughness  8.557575e-03
39   cat__gateway_ac1f09fffe06fcf2  6.550217e-03
7                   num__elevation  5.592362e-03
22  num__fresnel_obstruction_ratio  4.843328e-03
2            num__spreading_factor  4.351444e-03
28              num__unknown_ratio  3.906185e-03
26                num__water_ratio  2.941676e-03
35   cat__gateway_a840411eebb44150  2.536600e-03
27          num__residential_ratio  2.507375e-03
20            num__max_obstruction  2.203351e-03
32   cat__gateway_7276ff002e06029f  1.562875e-03
18              num__terrain_range  1.447215e-03
19          num__obstruction_ratio  1.085998e-03
21           num__mean_obstruction  9.805402e-04
40   cat__gateway_ac1f09fffe0fd629  9.325536e-04
44    cat__terrain_type_industrial  9.258665e-04
48       cat__terrain_type_unknown  7.576351e-04
45   cat__terrain_type_residential  6.207596e-04
31   cat__gateway_7276ff002e0507da  2.479060e-04
37   cat__gateway_ac1f09fffe00ab20  1.946673e-04
38   cat__gateway_ac1f09fffe00ab25  1.514256e-04
36   cat__gateway_a84041ffff1ec39f  1.265952e-04
49         cat__terrain_type_water  9.773065e-05
25               num__forest_ratio  4.098980e-05
47         cat__terrain_type_scrub  3.337776e-05
43         cat__terrain_type_grass  1.809893e-05
42        cat__terrain_type_forest  6.747524e-06
41   cat__gateway_ac1f09fffe0fd63b  6.417541e-06
46        cat__terrain_type_retail  1.091230e-06
34   cat__gateway_7276ff002e062cf2  9.835633e-07
50          cat__terrain_type_wood  7.153526e-07
1                   num__bandwidth  0.000000e+00

FEATURE IMPORTANCE AVEC PERMUTATION : 
                      feature  importance
17                terrain_max    0.855852
12                      slope    0.594322
29                    gateway    0.388132
10            elevation_angle    0.129914
0                   frequency    0.118720
9             delta_elevation    0.094341
8                gw_elevation    0.082720
16                terrain_min    0.063295
2            spreading_factor    0.031659
24     mean_fresnel_clearance    0.029499
14               terrain_mean    0.009252
13                  roughness    0.009103
23      min_fresnel_clearance    0.006886
6             log_distance_3d    0.006814
22  fresnel_obstruction_ratio    0.005851
4                log_distance    0.005586
5                 distance_3d    0.005220
11                       fspl    0.005077
7                   elevation    0.004877
3                    distance    0.004797
15                terrain_std    0.004556
27          residential_ratio    0.003428
28              unknown_ratio    0.003374
20            max_obstruction    0.001277
__________________________________________
26                water_ratio    0.000674
30               terrain_type    0.000197
19          obstruction_ratio    0.000048
1                   bandwidth    0.000000
25               forest_ratio   -0.000022
21           mean_obstruction   -0.000032
18              terrain_range   -0.000308

FEATURES enlevé : celles inf a  max obstruction
went from : RESULTS : RANDOM_FOREST
MAE  : 2.15 dBm
RMSE : 3.77 dBm
R²   : 0.8872
TO : RESULTS : RANDOM_FOREST
MAE  : 2.14 dBm
RMSE : 3.77 dBm
R²   : 0.8875
AND FROM : RESULTS : XGBOOST
MAE  : 2.33 dBm
RMSE : 4.20 dBm
R²   : 0.8602
TO : RESULTS : XGBOOST
MAE  : 2.36 dBm
RMSE : 4.24 dBm
R²   : 0.8577

Features maj :
added
    "delta_lat", 
    "delta_lon",
    "angle",
removed 
    # "distance",
    # "distance_3d",
    # "unknown_ratio",
    # "fspl"
    # "elevation",
   
TO RESULTS : RANDOM_FOREST
MAE : 2.12 dBm
RMSE : 3.77 dBm
R² : 0.8872
AVEC : 
                      feature  importance
15                terrain_max    0.800356
10                      slope    0.398399
20                    gateway    0.385218
0                   frequency    0.119552
8             delta_elevation    0.089288
7                gw_elevation    0.082437
9             elevation_angle    0.070411
14                terrain_min    0.065715
6                       angle    0.043304
18     mean_fresnel_clearance    0.034972
1            spreading_factor    0.031614
3             log_distance_3d    0.031401
4                   delta_lat    0.021302
2                log_distance    0.018730
12               terrain_mean    0.008000
19          residential_ratio    0.007417
11                  roughness    0.006889
17      min_fresnel_clearance    0.005978
16  fresnel_obstruction_ratio    0.003996
13                terrain_std    0.002767
5                   delta_lon    0.001093

Features finalisé.
choix du model, hyperparametres et k fold:
RESULTS : RANDOM_FOREST
MAE  : 2.11 dBm
RMSE : 3.42 dBm
R²   : 0.9073
{'model__n_estimators': 500, 'model__min_samples_split': 2, 'model__min_samples_leaf': 1, 'model__max_features': 'sqrt', 'model__max_depth': 20}
Best CV score: 0.8928582828174534

RESULTS : EXTRA_TREES
MAE  : 2.03 dBm
RMSE : 3.45 dBm
R²   : 0.9056
{'model__n_estimators': 1500, 'model__min_samples_split': 5, 'model__min_samples_leaf': 2, 'model__max_features': None, 'model__max_depth': 20}
Best CV score: 0.9043157603128187

RESULTS : XGBOOST : NUL
MAE  : 2.14 dBm
RMSE : 3.80 dBm
R²   : 0.8857
{'model__subsample': 0.8, 'model__n_estimators': 1000, 'model__max_depth': 10, 'model__learning_rate': 0.01, 'model__colsample_bytree': 1.0}
Best CV score:
0.8962056994438171

RESULTS : HIST_GRAD_BOOST : NUL
MAE  : 2.22 dBm
RMSE : 3.72 dBm
R²   : 0.8904
{'model__min_samples_leaf': 20, 'model__max_leaf_nodes': 31, 'model__max_depth': None, 'model__learning_rate': 0.1, 'model__l2_regularization': 0.0}
Best CV score:
0.8851964577354531

RESULTS : MLP_REG : NUL
MAE  : 2.58 dBm
RMSE : 4.19 dBm
R²   : 0.8609
{'model__hidden_layer_sizes': (100,), 'model__alpha': 0.01, 'model__activation': 'tanh'}
Best CV score:
0.8477885945374343

RESULTS : SVR : NUL
MAE  : 2.79 dBm
RMSE : 5.49 dBm
R²   : 0.7610
{'model__kernel': 'rbf', 'model__epsilon': 0.5, 'model__C': 10.0}
Best CV score:
0.7406420868442494

Les principales familles d'algorithmes de régression supervisée ont été évaluées : 
Bagging → RF, ExtraTrees
Boosting → XGBoost, HistGradientBoost
Réseau de neurones → MLP
Méthode à noyau → SVR

Les deux meilleurs modèles sont :
Random Forest
Extra Trees

comparaison : 
SUR SPATIAL SPLIT :
RESULTS : RANDOM_FOREST
MAE  : 21.98 dBm
RMSE : 25.50 dBm
R²   : -0.3532

RESULTS : EXTRA_TREES
MAE  : 24.26 dBm
RMSE : 27.51 dBm
R²   : -0.5754

SUR 5 fold shuffled : 
RESULTS : RANDOM_FOREST
R²   : 0.9065496122245399
MAE  : 2.0723521650301495
RMSE : 3.3343703140599117

RESULTS : EXTRA_TREES : MODEL FINAL
R²   : 0.9106026878497498
MAE  : 2.003640836176458
RMSE : 3.2613100891320825

Pour un mémoire/rapport je dirais :

Random Forest and Extra Trees achieved very similar performances. Extra Trees obtained the best average cross-validation scores (R²=0.911, MAE=2.00 dBm, RMSE=3.26 dBm) and was therefore selected as the final model.

C'est une justification tout à fait acceptable.

Concernant le std :

Si tu observes :

RF = légèrement plus stable
ET = légèrement plus précis

alors :

Si ton objectif est la meilleure prédiction

→ prends Extra Trees

Si ton objectif est la robustesse / reproductibilité

→ prends Random Forest




