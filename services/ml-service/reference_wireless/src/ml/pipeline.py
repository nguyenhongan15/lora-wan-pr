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

TARGET = "rssi"

NUMERIC_FEATURES = [
    # Radio
    # "snr", features not usable for prediction since not available at prediction time
    "frequency",
    # "bandwidth", // constant in our dataset
    "spreading_factor",

    # Geometry
    # "distance", //already in log_distance
    "log_distance",
    # "distance_3d", //already in log_distance_3d
    "log_distance_3d",

    "delta_lat", 
    "delta_lon",
    "angle",

    # Terrain elevation
    # "elevation",  //already in delta elev
    "gw_elevation",
    "delta_elevation",
    "elevation_angle",

    # Propagation
    # "fspl", //already in distances features
    "slope",
    "roughness",
    #Terrain
    "terrain_mean",
    "terrain_std",
    "terrain_min",
    "terrain_max",
    # "terrain_range", // low importance

    # "los", #Redondance with obstruction ratio (los = obstruction_ratio == 0)
    # "obstruction_ratio", //low importance
    # "max_obstruction",
    # "mean_obstruction", //low importance 
    "fresnel_obstruction_ratio",
    "min_fresnel_clearance",
    "mean_fresnel_clearance",

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

    # Models
    if model_type == "random_forest":
        model = RandomForestRegressor( #best parameters found
            n_estimators=500,
            max_depth=20,
            min_samples_split=2,
            min_samples_leaf=1,
            max_features="sqrt",
            random_state=42,
            n_jobs=-1
        )
    if model_type == "extra_trees":
        from sklearn.ensemble import ExtraTreesRegressor
        model = ExtraTreesRegressor(  #best parameters found
            n_estimators=1500,
            max_depth=20,
            min_samples_split=5,
            min_samples_leaf=2,
            max_features=None,
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


def prepare_data(df: pd.DataFrame):

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