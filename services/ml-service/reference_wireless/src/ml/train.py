import pandas as pd
import joblib
import numpy as np

from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from ml.pipeline import NUMERIC_FEATURES, CATEGORICAL_FEATURES, TARGET, build_pipeline, prepare_data

DATA_PATH = "../data/processed/devices_history_full.csv"


def train(model_type="random_forest"):

    print("Loading data...")
    df = pd.read_csv(DATA_PATH)

    # print("Train / test split...")
    # # Region split
    # df["region"] = np.where(
    #     df["lat"] > 16.7,
    #     "haiphong",
    #     "danang"
    # )
    # # Train = Da Nang
    # train_df = df[df["region"] == "danang"]
    # # Test = Hai Phong
    # test_df = df[df["region"] == "haiphong"]
    # # Prepare data
    # print("Preparing data...")
    # X_train, y_train = prepare_data(train_df)
    # X_test, y_test = prepare_data(test_df)

    X, y = prepare_data(df)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    print("Building pipeline...")
    pipeline = build_pipeline(model_type)

    print("Training model...")
    pipeline.fit(X_train, y_train)

    print("Predicting...")
    y_pred = pipeline.predict(X_test)

    feature_names = pipeline.named_steps["preprocessor"].get_feature_names_out()

    importances = pipeline.named_steps["model"].feature_importances_

    importance_df = pd.DataFrame({"feature": feature_names, "importance": importances})

    importance_df = importance_df.sort_values(by="importance", ascending=False)

    print(importance_df.head(20))
    # Metrics
    mae = mean_absolute_error(y_test, y_pred)
    rmse = mean_squared_error(y_test, y_pred) ** 0.5

    r2 = r2_score(y_test, y_pred)

    print("\nRESULTS : " + model_type.upper())
    print(f"MAE  : {mae:.2f} dBm")
    print(f"RMSE : {rmse:.2f} dBm")
    print(f"R²   : {r2:.4f}")

    print("Saving model...")
    joblib.dump(pipeline, f"ml/models/{model_type}_model.pkl")

    print("Done!")
