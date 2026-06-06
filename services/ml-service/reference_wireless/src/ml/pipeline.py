# src/ml/pipeline.py
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import (
    StandardScaler,
    OneHotEncoder
)

from sklearn.impute import SimpleImputer
from sklearn.ensemble import RandomForestRegressor

from processing.features import add_closest_point_features

TARGET = "rssi"

NUMERIC_FEATURES = [
    # Radio
    # "snr", features not usable for prediction since not available at prediction time
    "frequency", 
    # "bandwidth", // constant in our dataset
    "spreading_factor", 

    # Geometry
    # "distance", #close to distance 3d
    # "log_distance", #close to log distance 3d
    "distance_3d", 
    "log_distance_3d",

    "rssi_closest_point",
    "distance_closest_point",
    "closest_to_gw_distance",
    # "ratio_gateway_distance",

    # "rssi_closest_super_point",

    "neighbor_rssi_mean",
    "neighbor_rssi_weighted_mean",
    "neighbor_rssi_std",

    "neighbor_distance_mean",
    "neighbor_gw_distance_mean",
    # "neighbor_ratio_gateway_distance",

    "delta_lat", 
    "delta_lon",
    "angle",

    # Terrain elevation
    "elevation",  #already in delta elev
    "gw_elevation",
    "delta_elevation", 
    "elevation_angle",

    # Propagation
    # "fspl", #already in distances features
    "slope",
    "roughness",
    #Terrain
    "terrain_mean",
    "terrain_std",
    "terrain_min", #low importance
    "terrain_max",
    "terrain_range", # low importance

    # "los", #Redondance with obstruction ratio (los = obstruction_ratio == 0)
    # "obstruction_ratio", #//low importance
    "max_obstruction", #low importance
    # "mean_obstruction", #//low importance 
    "fresnel_obstruction_ratio", #low importance
    "min_fresnel_clearance", #low importance
    "mean_fresnel_clearance", #low importance

    # Land use ratios
    # "forest_ratio", // distribution too low to be useful
    # "water_ratio", // distribution too low to be useful
    "residential_ratio",
    # "unknown_ratio", //arleady in residential ratio
]

CATEGORICAL_FEATURES = [
    "gateway", #train in danang and test in hai phong so useless in that case 
    # "device", #same idea : not specific to propagation (and not available at prediction time ?)
    # "terrain_type", //low importance
]

def build_pipeline(model_type="random_forest"):

    # Numeric preprocessing
    numeric_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler())
        ]
    )

    # Categorical preprocessing
    categorical_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            (
                "encoder",
                OneHotEncoder(
                    handle_unknown="ignore"
                )
            )
        ]
    )

    # Full preprocessing
    preprocessor = ColumnTransformer(
        transformers=[
            (
                "num",
                numeric_transformer,
                NUMERIC_FEATURES
            ),

            (
                "cat",
                categorical_transformer,
                CATEGORICAL_FEATURES
            ),
        ]
    )

    if model_type == "extra_trees":
        from sklearn.ensemble import ExtraTreesRegressor
        model = ExtraTreesRegressor(  #best parameters found
            n_estimators=650,
            max_depth=18,
            min_samples_split=10,
            min_samples_leaf=1,
            max_features=0.7,
            random_state=42,
            n_jobs=-1
        )

    # Final pipeline
    pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("model", model)
        ]
    )

    return pipeline


def prepare_data(
    df: pd.DataFrame,
    reference_df: pd.DataFrame = None,
    MIN_DISTANCE=0.1,
    K=9,
    K_SEARCH=11,
    GW_DISTANCE_WEIGHT=1.1
):

    add_closest_point_features(
        df,
        reference_df=reference_df,
        MIN_DISTANCE=MIN_DISTANCE,
        K=K,
        K_SEARCH=K_SEARCH,
        GW_DISTANCE_WEIGHT=GW_DISTANCE_WEIGHT
    )

    X = df[
        NUMERIC_FEATURES +
        CATEGORICAL_FEATURES
    ]

    y = df[TARGET]

    return X, y


def get_feature_names(pipeline):

    preprocessor = pipeline.named_steps["preprocessor"]

    feature_names = []

    feature_names.extend(NUMERIC_FEATURES)

    cat_encoder = (
        preprocessor
        .named_transformers_["cat"]
        .named_steps["encoder"]
    )

    cat_names = cat_encoder.get_feature_names_out(
        CATEGORICAL_FEATURES
    )

    feature_names.extend(cat_names)

    return feature_names