def clean_data(df):
    # enlever GPS invalides
    df = df[(df["lat"] != 0) & (df["lon"] != 0)]

    # enlever lignes sans SNR : pas obligé si on veut plus de données sans utliser snr
    df = df.dropna(subset=["snr"])

    df = df.copy()
    return df
