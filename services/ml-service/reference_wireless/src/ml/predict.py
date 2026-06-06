import joblib
import pandas as pd

from ml.pipeline import prepare_data

def load_model(model_type="random_forest"):
    return joblib.load(f"ml/models/{model_type}_model.pkl")

def predict(df: pd.DataFrame, model_type="random_forest", reference_df: pd.DataFrame = None):

    if reference_df is None:
        raise ValueError(
            "reference_df must be provided when using nearest-neighbor features."
        )

    model = load_model(model_type)

    X, _ = prepare_data(
        df,
        reference_df=reference_df,
        MIN_DISTANCE=0.1,
        K=9,
        K_SEARCH=11,
        GW_DISTANCE_WEIGHT=1.1
    )

    return model.predict(X)