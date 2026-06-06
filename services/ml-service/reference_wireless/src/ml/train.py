import pandas as pd
import numpy as np
import joblib

from sklearn.inspection import permutation_importance
from sklearn.model_selection import KFold, ParameterSampler, RandomizedSearchCV, cross_validate, train_test_split, cross_val_score
from sklearn.metrics import (
    root_mean_squared_error,
    mean_absolute_error,
    mean_squared_error,
    r2_score
)

from ml import pipeline
from ml.pipeline import (
    NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    TARGET,
    build_pipeline,
    prepare_data
)
from processing.features import add_closest_point_features

DATA_PATH = "../data/processed/devices_history_full.csv"


def train(
    model_type="extra_trees",

    MIN_DISTANCE=0.1,
    K=9,
    K_SEARCH=11,
    GW_DISTANCE_WEIGHT=1.1,

    show_importance=True,
    save_model=True
):

    print("Loading data...")
    df = pd.read_csv(DATA_PATH)

    kf = KFold(
        n_splits=5,
        shuffle=True,
        random_state=42
    )
    
    r2_scores = []
    mae_scores = []
    rmse_scores = []

    pipeline = build_pipeline("extra_trees")

    for train_idx, test_idx in kf.split(df):

        train_df = df.iloc[train_idx].copy()
        test_df = df.iloc[test_idx].copy()

        X_train, y_train = prepare_data(
            train_df,
            reference_df=train_df,
            MIN_DISTANCE=0.1,
            K=9,
            K_SEARCH=11,
            GW_DISTANCE_WEIGHT=1.1
        )

        X_test, y_test = prepare_data(
            test_df,
            reference_df=train_df,
            MIN_DISTANCE=0.1,
            K=9,
            K_SEARCH=11,
            GW_DISTANCE_WEIGHT=1.1
        )

        pipeline.fit(X_train, y_train)

        pred = pipeline.predict(X_test)

        r2 = r2_score(
            y_test,
            pred
        )

        mae = mean_absolute_error(
            y_test,
            pred
        )

        rmse = root_mean_squared_error(
            y_test,
            pred
        )

        r2_scores.append(r2)
        mae_scores.append(mae)
        rmse_scores.append(rmse)


    print(
        f"R²   : "
        f"{np.mean(r2_scores):.4f}"
        f" ± "
        f"{np.std(r2_scores):.4f}"
        f"  MAE  : "
        f"{np.mean(mae_scores):.2f} dBm"
        f"  RMSE : "
        f"{np.mean(rmse_scores):.2f} dBm"
    )

    # ------------------------
    # Final training
    # ------------------------

    print("Training final model on full data...")

    X, y = prepare_data(
        df,
        reference_df=df,
        MIN_DISTANCE=MIN_DISTANCE,
        K=K,
        K_SEARCH=K_SEARCH,
        GW_DISTANCE_WEIGHT=GW_DISTANCE_WEIGHT
    )

    pipeline = build_pipeline(
        model_type
    )

    pipeline.fit(X, y)


    # # ------------------------
    # # Save final model
    # # ------------------------

    if save_model:
    
        print(
            "Saving model..."
        )
    
        joblib.dump(
            pipeline,
            f"ml/models/{model_type}_model.pkl"
        )

    print("Done.")
