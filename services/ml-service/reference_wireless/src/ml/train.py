import pandas as pd
import joblib

from sklearn.inspection import permutation_importance
from sklearn.model_selection import KFold, RandomizedSearchCV, cross_validate, train_test_split, cross_val_score
from sklearn.metrics import (
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

DATA_PATH = "../data/processed/devices_history_full.csv"


def train(model_type="random_forest"):

    print("Loading data...")
    df = pd.read_csv(DATA_PATH)
    X, y = prepare_data(df)

    print("Building pipeline...")
    pipeline = build_pipeline(model_type)

    print("Cross-validating...")
    scores = cross_validate(
        pipeline,
        X,
        y,
        cv=KFold(
            n_splits=5,
            shuffle=True,
            random_state=42
        ),
        scoring={
            "r2": "r2",
            "mae": "neg_mean_absolute_error",
            "rmse": "neg_root_mean_squared_error"
        },
        n_jobs=-1
    )

    # Spatial train-test split (by cities)
    # train = df[df["lat"] <= 16.7]   # Da Nang
    # test  = df[df["lat"] > 16.7]    # Hai Phong
    # X_train, y_train = prepare_data(train)
    # X_test, y_test = prepare_data(test)

    #TO TEST HYPERPARAMETERS TUNING
    #param_grid = { ... } # Define your hyperparameters grid here
    # search = RandomizedSearchCV(
    #     estimator=pipeline,
    #     param_distributions=param_grid,
    #     n_iter=20,
    #     cv=5,
    #     scoring="r2",
    #     n_jobs=-1,
    #     random_state=42
    # )
    # print("Training model...")
    # search.fit(X_train, y_train)
    # pipeline = search.best_estimator_
    # print("Best params:")
    # print(search.best_params_)

    # print("Best CV score:")
    # print(search.best_score_)

    #TO TEST FEATURES IMPORTANCES
    # result = permutation_importance(
    #     pipeline,
    #     X_test,
    #     y_test,
    #     n_repeats=10,
    #     random_state=42,
    #     scoring="r2"
    # )
    # importance_df = pd.DataFrame({
    #     "feature": X_test.columns,
    #     "importance": result.importances_mean
    # }).sort_values(
    #     "importance",
    #     ascending=False
    # )
    # print(importance_df)

        # Metrics (train basis 20%)
    # mae = mean_absolute_error(y_test, y_pred)
    # rmse = mean_squared_error(
    #     y_test,
    #     y_pred
    # ) ** 0.5
    # r2 = r2_score(y_test, y_pred)

    print("\nRESULTS : "+model_type.upper())
    # print(f"MAE  : {mae:.2f} dBm") #basic split 20%
    # print(f"RMSE : {rmse:.2f} dBm")
    # print(f"R²   : {r2:.4f}")
    print("R²   :", scores["test_r2"].mean())
    print("MAE  :", -scores["test_mae"].mean())
    print("RMSE :", -scores["test_rmse"].mean())

    pipeline.fit(X, y)

    print("Saving model...")
    joblib.dump(
        pipeline,
        f"ml/models/{model_type}_model.pkl"
    )

    print("Done!")
