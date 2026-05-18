import joblib
import pandas as pd

from ml.pipeline import prepare_data


def load_model(model_type="random_forest"):
    return joblib.load(f"ml/models/{model_type}_model.pkl")


def predict(df: pd.DataFrame, model_type="random_forest"):
    model = load_model(model_type)
    X, _ = prepare_data(df)
    predictions = model.predict(X)

    return predictions
