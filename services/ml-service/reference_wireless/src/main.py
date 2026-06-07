from api.fetch_data import fetch_device_history, fetch_latest_devices
from processing.cleaning import clean_data
from processing.features import add_basic_features, add_closest_point_features
from processing.parser import parse_devices
from processing.terrain import add_terrain_features
from ml.predict import predict
from ml.train import train
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
from build_reference_dataset import build_reference_dataset
from build_gateways_dataset import build_gateways_dataset


DATA_PATH = "../data/processed/devices_history_full.csv"
DATA_PATH_1 = "../data/processed/devices_history_1.csv"
DATA_PATH_2 = "../data/processed/devices_history_2.csv"

FORCE_FETCH = False
ADD_FEATURES = False
TRAIN =False
MODEL_TYPE = "extra_trees"
SHOW_PLOTS = False
SAVE_DATA_WITH_FEATURES = False

def main():
    if(os.path.exists(DATA_PATH) and not FORCE_FETCH):
        print("Loading local data...")
        df = pd.read_csv(DATA_PATH)
    else:
        if os.path.exists(DATA_PATH_1) and not FORCE_FETCH:
            print("Loading local data 1...")
            df = pd.read_csv(DATA_PATH_1)
        else:
            print("Fetching data 1 from API...")

            devices = ["board01", "node3", "node01"]
            all_data = []

            for d in devices:
                print(f"Fetching {d}...")
                data = fetch_device_history(d)
                all_data.extend(data)

            print("Parsing data...")
            df = parse_devices(all_data)
            df = clean_data(df)
            df.to_csv(DATA_PATH_1, index=False)
            print("Data 1 saved!")

        if(os.path.exists(DATA_PATH_2) and not FORCE_FETCH):
            print("Loading local data 2...")
            df2 = pd.read_csv(DATA_PATH_2)
        else:
            print("Fetching data 2 from API...")

            devices = ["board01", "node3", "node01"] # (only node01 for now)
            all_data = []

            for d in devices:
                print(f"Fetching {d}...")
                data = fetch_device_history(d, type=2)
                all_data.extend(data)

            print("Parsing data...")
            df2 = parse_devices(all_data)
            df2 = clean_data(df2)
            df2.to_csv(DATA_PATH_2, index=False)
            print("Data 2 saved!")
        df = pd.concat([df, df2], ignore_index=True)
        df = df.drop_duplicates()
        df.to_csv(DATA_PATH, index=False)
        print("Full data saved!")
        print(df.describe())
    if(ADD_FEATURES):
        print("Adding features...")
        # df = add_basic_features(df)
        # df = add_terrain_features(df)
        df.to_csv(DATA_PATH, index=False)
        print("Features added and data saved!")

    if TRAIN:
        train(MODEL_TYPE)

    if SAVE_DATA_WITH_FEATURES:
        print("Adding features for predictions...")
        df_with_features = df.copy()
        df_with_features = add_closest_point_features(
            df_with_features,
            reference_df=df_with_features
        )
        df_with_features.to_csv(
            "../data/processed/data_with_closest_points_features.csv",
            index=False
        )
        print("Features added and data saved!")

    print("Predicting...")
    predictions = predict(df, MODEL_TYPE, df)
    df["predicted_rssi"] = predictions

    # Worst predictions
    df["error"] = (df["predicted_rssi"] - df["rssi"]).abs()

    worst_10 = (
        df
        .sort_values("error", ascending=False)
        .head(10)
    )

    print("\n10 worst predictions:")
    print(
        worst_10[
            [
                "lat",
                "lon",
                "gateway_id",
                "distance",
                "rssi",
                "predicted_rssi",
                "error"
            ]
        ]
    )
    print(f"Standard deviation of errors: {df['error'].std()}")

    if SHOW_PLOTS:

        gateways = df["gateway_id"].astype(str)
        unique = gateways.unique()

        cmap = plt.get_cmap("tab10")
        colors = {
            g: cmap(i % cmap.N)
            for i, g in enumerate(unique)
        }

        # --------------------------------------------------
        # Closest point RSSI vs Actual RSSI
        # --------------------------------------------------

        plt.figure(figsize=(6, 6))

        plt.scatter(
            df["rssi"],
            df["rssi_closest_point"],
            alpha=0.4
        )

        lo = min(
            df["rssi"].min(),
            df["rssi_closest_point"].min()
        )
        hi = max(
            df["rssi"].max(),
            df["rssi_closest_point"].max()
        )

        plt.plot([lo, hi], [lo, hi], "r--")

        plt.xlabel("Actual RSSI")
        plt.ylabel("Closest point RSSI")
        plt.title("Closest Point RSSI vs Actual RSSI")
        plt.tight_layout()
        plt.show()

        # --------------------------------------------------
        # Predicted vs Actual
        # --------------------------------------------------

        plt.figure(figsize=(6, 6))

        for g in unique:
            mask = gateways == g

            plt.scatter(
                df.loc[mask, "rssi"],
                df.loc[mask, "predicted_rssi"],
                alpha=0.5,
                label=str(g),
                color=colors[g]
            )

        lo = min(
            df["rssi"].min(),
            df["predicted_rssi"].min()
        )
        hi = max(
            df["rssi"].max(),
            df["predicted_rssi"].max()
        )

        plt.plot([lo, hi], [lo, hi], "r--")

        plt.xlabel("Actual RSSI")
        plt.ylabel("Predicted RSSI")
        plt.title("Predicted vs Actual RSSI")
        plt.legend(title="Gateway")
        plt.tight_layout()
        plt.show()

        # --------------------------------------------------
        # Error histogram
        # --------------------------------------------------

        error = (
            df["predicted_rssi"]
            - df["rssi"]
        )

        plt.figure(figsize=(8, 5))

        plt.hist(
            error,
            bins=50,
            alpha=0.7
        )

        plt.axvline(
            0,
            color="black",
            linestyle="--"
        )

        plt.xlabel("Prediction Error (dBm)")
        plt.ylabel("Count")
        plt.title("Prediction Error Distribution")
        plt.tight_layout()
        plt.show()

        # --------------------------------------------------
        # Absolute Error vs Gateway Distance
        # --------------------------------------------------

        abs_error = np.abs(error)

        plt.figure(figsize=(8, 5))

        plt.scatter(
            df["distance"],
            abs_error,
            alpha=0.3
        )

        plt.xlabel("Gateway Distance (m)")
        plt.ylabel("Absolute Error (dBm)")
        plt.title("Absolute Error vs Gateway Distance")
        plt.tight_layout()
        plt.show()

        # --------------------------------------------------
        # Absolute Error vs Closest Point Distance
        # --------------------------------------------------

        plt.figure(figsize=(8, 5))

        plt.scatter(
            df["distance_closest_point"],
            abs_error,
            alpha=0.3
        )

        plt.xlabel("Closest Point Distance (m)")
        plt.ylabel("Absolute Error (dBm)")
        plt.title("Absolute Error vs Closest Point Distance")
        plt.tight_layout()
        plt.show()

        # --------------------------------------------------
        # Residuals
        # --------------------------------------------------

        plt.figure(figsize=(8, 5))

        plt.scatter(
            df["rssi"],
            error,
            alpha=0.3
        )

        plt.axhline(
            0,
            color="black",
            linestyle="--"
        )

        plt.xlabel("Actual RSSI")
        plt.ylabel("Residual (Prediction - Actual)")
        plt.title("Residuals vs Actual RSSI")
        plt.tight_layout()
        plt.show()

if __name__ == "__main__":
    main()