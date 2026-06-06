def clean_data(df):
    # enlever GPS invalides
    df = df[(df["lat"] != 0) & (df["lon"] != 0)]
    
    eps = 1e-6
    mask = (
        (
            (abs(df["lat"] - 16.092370) < eps) &
            (abs(df["lon"] - 108.141370) < eps) &
            (df["gateway_id"] == 9) &
            (df["rssi"].isin([-90, -95, -109, -112,-107]))
        )
        |
        (
            (abs(df["lat"] - 20.918076) < eps) &
            (abs(df["lon"] - 106.638658) < eps) &
            (df["gateway_id"] == 0) &
            (df["rssi"].isin([-114, -84]))
        )
    )
    df = df[~mask]
    
    df = df.copy() 
    return df