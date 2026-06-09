from api.fetch_data import fetch_device_history, fetch_latest_devices
from processing.cleaning import clean_data
from processing.features import add_basic_features
from processing.parser import parse_devices
from processing.terrain import add_terrain_features
from ml.predict import predict
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os


DATA_PATH = "../data/processed/devices_history_full.csv"
DATA_PATH_1 = "../data/processed/devices_history_1.csv"
DATA_PATH_2 = "../data/processed/devices_history_2.csv"

FORCE_FETCH = False
ADD_FEATURES = False
TRAIN = False
MODEL_TYPE = "random_forest" 
TRAIN_2 = False
MODEL_TYPE_2 = "extra_trees" 
SHOW_PLOTS = True

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
    
    if(TRAIN):
        from ml.train import train
        train(MODEL_TYPE)
    if(TRAIN_2):
        from ml.train import train
        train(MODEL_TYPE_2)

    print("Predicting for model 1...")
    predictions = predict(df, MODEL_TYPE)
    df["predicted_rssi"] = predictions
    print("Predictions for model 2...")
    predictions_2 = predict(df, MODEL_TYPE_2)
    df["predicted_rssi_2"] = predictions_2

    if(SHOW_PLOTS):
        # Plot predicted vs actual by gateway 1 
        plt.figure(figsize=(6,6))
        # color by gateway_id
        gateways = df["gateway_id"].astype(str)
        unique = gateways.unique()
        cmap = plt.get_cmap("tab10")
        colors = {g: cmap(i % cmap.N) for i, g in enumerate(unique)}
        for g in unique:
            mask = gateways == g
            plt.scatter(df.loc[mask, "rssi"], df.loc[mask, "predicted_rssi"],
                        alpha=0.6, label=str(g), color=colors[g])

        lo = min(df["rssi"].min(), df["predicted_rssi"].min())
        hi = max(df["rssi"].max(), df["predicted_rssi"].max())
        plt.plot([lo, hi], [lo, hi], "r--")
        plt.xlabel("Actual rssi")
        plt.ylabel("Predicted rssi")
        plt.title("Predicted vs Actual rssi")
        plt.tight_layout()
        # plt.savefig("pred_vs_actual.png")
        plt.show()

        ##Plot predicted vs actual by gateway 2
        plt.figure(figsize=(6,6))
        for g in unique:
            mask = gateways == g
            plt.scatter(df.loc[mask, "rssi"], df.loc[mask, "predicted_rssi_2"],
                        alpha=0.6, label=str(g), color=colors[g])
        lo = min(df["rssi"].min(), df["predicted_rssi_2"].min())
        hi = max(df["rssi"].max(), df["predicted_rssi_2"].max())
        plt.plot([lo, hi], [lo, hi], "r--")
        plt.xlabel("Actual rssi")
        plt.ylabel("Predicted rssi 2")
        plt.title("Predicted vs Actual rssi (Model 2)")
        plt.tight_layout()
        # plt.savefig("pred_vs_actual_2.png")
        plt.show()

        ##Plot error 1 vs error 2
        plt.figure(figsize=(6,6))
        plt.scatter(df["predicted_rssi"] - df["rssi"], df["predicted_rssi_2"] - df["rssi"], alpha=0.6)
        plt.xlabel("Error Model 1")
        plt.ylabel("Error Model 2")
        plt.title("Error Comparison")
        plt.tight_layout()
        # plt.savefig("error_comparison.png")
        plt.show()

        ##Plot predicted vs actual by models
        plt.figure(figsize=(6,6))
        plt.scatter(df["rssi"], df["predicted_rssi"], alpha=0.6, label="Model 1")
        plt.scatter(df["rssi"], df["predicted_rssi_2"], alpha=0.6, label="Model 2")
        lo = min(df["rssi"].min(), df["predicted_rssi"].min(), df["predicted_rssi_2"].min())
        hi = max(df["rssi"].max(), df["predicted_rssi"].max(), df["predicted_rssi_2"].max())
        plt.plot([lo, hi], [lo, hi], "r--")
        plt.xlabel("Actual rssi")
        plt.ylabel("Predicted rssi")
        plt.title("Predicted vs Actual rssi (Both Models)")
        plt.legend()
        plt.tight_layout()
        # plt.savefig("pred_vs_actual_both.png")
        plt.show()

        #ERROR DISTRIBUTION
        error_rf = df["predicted_rssi"] - df["rssi"]
        error_et = df["predicted_rssi_2"] - df["rssi"]

        plt.figure(figsize=(8,5))
        plt.hist(error_rf, bins=50, alpha=0.5, label="RF")
        plt.hist(error_et, bins=50, alpha=0.5, label="ET")
        plt.axvline(0, color="black", linestyle="--")
        plt.xlabel("Prediction Error (dBm)")
        plt.ylabel("Count")
        plt.title("Error Distribution")
        plt.legend()
        plt.show()

        #BOX PLOT OF ERRORS
        plt.figure(figsize=(6,5))
        plt.boxplot(
            [
                error_rf,
                error_et
            ],
            labels=["RF", "ET"]
        )

        plt.ylabel("Prediction Error (dBm)")
        plt.title("Error Distribution by Model")
        plt.show()

        #ERROR BY DISTANCE
        abs_err_rf = np.abs(error_rf)
        abs_err_et = np.abs(error_et)
        plt.figure(figsize=(8,5))
        plt.scatter(
            df["distance"],
            abs_err_rf,
            alpha=0.3,
            label="RF"
        )
        plt.scatter(
            df["distance"],
            abs_err_et,
            alpha=0.3,
            label="ET"
        )
        plt.xlabel("Distance (m)")
        plt.ylabel("Absolute Error (dBm)")
        plt.title("Error vs Distance")
        plt.legend()
        plt.show()

        plt.figure(figsize=(8,5))

        #RSSI VS ERROR
        plt.scatter(
            df["rssi"],
            error_rf,
            alpha=0.3,
            label="RF"
        )

        plt.scatter(
            df["rssi"],
            error_et,
            alpha=0.3,
            label="ET"
        )

        plt.axhline(0, color="black", linestyle="--")

        plt.xlabel("Actual RSSI")
        plt.ylabel("Residual")
        plt.title("Residuals vs Actual RSSI")
        plt.legend()
        plt.show()


if __name__ == "__main__":
    main()