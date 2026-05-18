# src/ml/pipeline.py
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, OneHotEncoder

from sklearn.impute import SimpleImputer
from sklearn.ensemble import RandomForestRegressor

TARGET = "rssi"

NUMERIC_FEATURES = [
    # Radio
    # "snr", features not usable for prediction since not available at prediction time
    "frequency",
    "bandwidth",
    "spreading_factor",
    # Geometry
    "distance",
    "log_distance",
    "distance_3d",
    "log_distance_3d",
    # "delta_lat", #too specific ?
    # "delta_lon",
    # "angle",
    # Terrain elevation
    "elevation",
    "gw_elevation",
    "delta_elevation",
    "elevation_angle",
    # Propagation
    "fspl",
    "slope",
    "roughness",
    # Terrain
    "terrain_mean",
    "terrain_std",
    "terrain_min",
    "terrain_max",
    "terrain_range",
    # "los", Redondance with obstruction ratio (los = obstruction_ratio == 0)
    "obstruction_ratio",
    "max_obstruction",
    "mean_obstruction",
    "fresnel_obstruction_ratio",
    "min_fresnel_clearance",
    "mean_fresnel_clearance",
    # Land use ratios
    "forest_ratio",
    "water_ratio",
    "residential_ratio",
    "unknown_ratio",
]

CATEGORICAL_FEATURES = [
    "gateway",  # train in danang and test in hai phong so useless in that case
    # "device", #same idea : not specific to propagation (and not available at prediction time ?)
    "terrain_type",
]


def build_pipeline(model_type="random_forest"):

    # Numeric preprocessing
    numeric_transformer = Pipeline(
        steps=[("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]
    )

    # Categorical preprocessing
    categorical_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore")),
        ]
    )

    # Full preprocessing
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", numeric_transformer, NUMERIC_FEATURES),
            ("cat", categorical_transformer, CATEGORICAL_FEATURES),
        ]
    )

    # Models
    if model_type == "random_forest":
        model = RandomForestRegressor(n_estimators=200, max_depth=20, random_state=42, n_jobs=-1)
    if model_type == "xgboost":
        from xgboost import XGBRegressor

        model = XGBRegressor(n_estimators=200, max_depth=20, random_state=42, n_jobs=-1)

    # Final pipeline
    pipeline = Pipeline(steps=[("preprocessor", preprocessor), ("model", model)])

    return pipeline


def prepare_data(df: pd.DataFrame):

    X = df[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    y = df[TARGET]

    return X, y


def get_feature_names(pipeline):

    preprocessor = pipeline.named_steps["preprocessor"]

    feature_names = []

    feature_names.extend(NUMERIC_FEATURES)

    cat_encoder = preprocessor.named_transformers_["cat"].named_steps["encoder"]

    cat_names = cat_encoder.get_feature_names_out(CATEGORICAL_FEATURES)

    feature_names.extend(cat_names)

    return feature_names
