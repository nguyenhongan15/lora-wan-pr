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







