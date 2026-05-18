from api.fetch_data import fetch_device_history, fetch_latest_devices
from processing.cleaning import clean_data
from processing.features import add_basic_features
from processing.parser import parse_devices
from processing.terrain import add_terrain_features
from ml.predict import predict
import pandas as pd
import matplotlib.pyplot as plt
import os


DATA_PATH = "../data/processed/devices_history_full.csv"
DATA_PATH_1 = "../data/processed/devices_history_1.csv"
DATA_PATH_2 = "../data/processed/devices_history_2.csv"

FORCE_FETCH = False
ADD_FEATURES = False
TRAIN = False
MODEL_TYPE = "random_forest"  # "random_forest", "xgboost", "lightgbm" ?
TRAIN_2 = True
MODEL_TYPE_2 = "xgboost"  # "random_forest", "xgboost", "lightgbm" ?


def main():
    if os.path.exists(DATA_PATH) and not FORCE_FETCH:
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

        if os.path.exists(DATA_PATH_2) and not FORCE_FETCH:
            print("Loading local data 2...")
            df2 = pd.read_csv(DATA_PATH_2)
        else:
            print("Fetching data 2 from API...")

            devices = ["board01", "node3", "node01"]  # (only node01 for now)
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
    if ADD_FEATURES:
        print("Adding features...")
        # df = add_basic_features(df)
        # df = add_terrain_features(df)
        df.to_csv(DATA_PATH, index=False)
        print("Features added and data saved!")

    if TRAIN:
        from ml.train import train

        train(MODEL_TYPE)
    if TRAIN_2:
        from ml.train import train

        train(MODEL_TYPE_2)

    print("Predicting for model 1...")
    predictions = predict(df, MODEL_TYPE)
    df["predicted_rssi"] = predictions
    print("Predictions for model 2...")
    predictions_2 = predict(df, MODEL_TYPE_2)
    df["predicted_rssi_2"] = predictions_2

    # Plot predicted vs actual by gateway 1
    plt.figure(figsize=(6, 6))
    # color by gateway_id
    gateways = df["gateway_id"].astype(str)
    unique = gateways.unique()
    cmap = plt.get_cmap("tab10")
    colors = {g: cmap(i % cmap.N) for i, g in enumerate(unique)}
    for g in unique:
        mask = gateways == g
        plt.scatter(
            df.loc[mask, "rssi"],
            df.loc[mask, "predicted_rssi"],
            alpha=0.6,
            label=str(g),
            color=colors[g],
        )

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
    plt.figure(figsize=(6, 6))
    for g in unique:
        mask = gateways == g
        plt.scatter(
            df.loc[mask, "rssi"],
            df.loc[mask, "predicted_rssi_2"],
            alpha=0.6,
            label=str(g),
            color=colors[g],
        )
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
    plt.figure(figsize=(6, 6))
    plt.scatter(df["predicted_rssi"] - df["rssi"], df["predicted_rssi_2"] - df["rssi"], alpha=0.6)
    plt.xlabel("Error Model 1")
    plt.ylabel("Error Model 2")
    plt.title("Error Comparison")
    plt.tight_layout()
    # plt.savefig("error_comparison.png")
    plt.show()

    ##Plot predicted vs actual by models
    plt.figure(figsize=(6, 6))
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


if __name__ == "__main__":
    main()
