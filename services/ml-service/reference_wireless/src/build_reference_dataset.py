import pandas as pd

REFERENCE_COLUMNS = [
    "lat",
    "lon",
    "gateway",
    "gateway_id",
    "gw_lat",
    "gw_lon",
    "rssi",
    "distance_3d",
    "closest_to_gw_distance",
]

def build_reference_dataset(
    input_csv="../data/processed/data_with_closest_points_features.csv",
    output_csv="../data/processed/reference_points.csv",
):

    df = pd.read_csv(input_csv)

    reference_df = (
        df[REFERENCE_COLUMNS]
        .copy()
        .reset_index(drop=True)
    )

    reference_df.to_csv(output_csv, index=False)

    print(f"Saved {len(reference_df)} rows")