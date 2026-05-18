import osmnx as ox
from shapely.geometry import Polygon

tags = {"landuse": True, "natural": True}

# bounds2=(106.05, 20.65,106.65, 20.92 )
polygon = Polygon([(106.05, 20.65), (106.65, 20.65), (106.65, 20.92), (106.05, 20.92)])

gdf = ox.features_from_polygon(polygon, tags=tags)

gdf = gdf[gdf.geometry.notnull()]
gdf = gdf[gdf.is_valid]
gdf = gdf[~gdf.geometry.is_empty]

gdf.to_file("../data/terrain/landuse2.geojson")

print(gdf.head())
