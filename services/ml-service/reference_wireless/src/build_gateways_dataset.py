import pandas as pd


GATEWAY_COLUMNS = [
    "gateway",
    "gateway_id",
    "gw_lat",
    "gw_lon",
    "gw_elevation",
]


def build_gateways_dataset(
    input_csv="../data/processed/data_with_closest_points_features.csv",
    output_csv="../data/processed/gateways.csv",
):

    df = pd.read_csv(input_csv)

    gateways_df = (
        df[GATEWAY_COLUMNS]
        .drop_duplicates(subset=["gateway"])
        .sort_values("gateway")
        .reset_index(drop=True)
    )

    gateways_df.to_csv(output_csv, index=False)

    print(f"Saved {len(gateways_df)} gateways to {output_csv}")