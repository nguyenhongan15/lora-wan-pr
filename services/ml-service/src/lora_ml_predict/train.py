import os
import logging
import asyncio
import psycopg
import pandas as pd
import numpy as np
import xgboost as xgb
import joblib
from pathlib import Path

# Workspace imports
from lora_coverage_api.application.itu.itur_p1812 import Stage1ItuModel
from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend
from lora_coverage_api.domain.coverage import Target, Gateway
from lora_ml_predict.app import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("ml_train")

def fetch_data(db_url: str) -> pd.DataFrame:
    query = """
    SELECT
        time, rssi, frequency_mhz, spreading_factor as sf,
        ST_Y(location::geometry) as lat, ST_X(location::geometry) as lon,
        ST_Y(gw_location::geometry) as gw_lat, ST_X(gw_location::geometry) as gw_lon,
        gw_altitude_m as gw_alt, gw_antenna_height_m as gw_ant_h,
        gw_antenna_gain_dbi as gw_gain, gw_tx_power_dbm as gw_tx_p
    FROM ts.survey_training
    WHERE is_valid = true
    """
    with psycopg.connect(db_url) as conn:
        return pd.read_sql_query(query, conn)

async def process_features(df: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """Calcule le RSSI Stage 1 et extrait les features en parallèle."""
    backend = CrcCovlibBackend(
        dem_directory=settings.dem_directory,
        surface_dem_directory=settings.surface_dem_directory
    )
    model_s1 = Stage1ItuModel(backend=backend)
    logger.info(f"Calcul des cibles Stage 1 pour {len(df)} lignes...")

    async def _predict_row(row):
        target = Target(
            latitude=row['lat'], longitude=row['lon'],
            spreading_factor=int(row['sf']), frequency_mhz=row['frequency_mhz']
        )
        gateway = Gateway(
            id="train-tmp", code="TMP", name="Temp",
            latitude=row['gw_lat'], longitude=row['gw_lon'],
            altitude_m=row['gw_alt'], antenna_height_m=row['gw_ant_h'],
            antenna_gain_dbi=row['gw_gain'], tx_power_dbm=row['gw_tx_p'],
            frequency_mhz=row['frequency_mhz']
        )
        pred = await model_s1.predict_coverage(target, gateway)
        return pred.rssi_dbm if pred else np.nan

    tasks = [_predict_row(row) for _, row in df.iterrows()]
    df['rssi_stage1'] = await asyncio.gather(*tasks)
    
    df['residual_target'] = df['rssi'] - df['rssi_stage1']
    return df.dropna(subset=['residual_target'])

def train():
    settings = Settings()
    df_raw = fetch_data(settings.db_url)
    df_raw['time'] = pd.to_datetime(df_raw['time'])

    # Split: Train/Val (Nov-Dec 2025), Test (Jan-Feb 2026)
    train_mask = (df_raw['time'] >= "2025-11-01") & (df_raw['time'] <= "2025-12-31")
    test_mask = (df_raw['time'] >= "2026-01-01") & (df_raw['time'] <= "2026-02-28")

    df_train_raw = df_raw[train_mask].copy()
    df_test_raw = df_raw[test_mask].copy()

    # Résolution de la boucle asyncio
    loop = asyncio.get_event_loop()
    df_train = loop.run_until_complete(process_features(df_train_raw, settings))
    df_test = loop.run_until_complete(process_features(df_test_raw, settings))

    # Feature Selection (Doit matcher strictement avec les clés de app.py)
    feature_cols = [
        "lat", "lon", "sf", "frequency_mhz",
        "gw_lat", "gw_lon", "gw_alt", "gw_ant_h", "gw_gain", "gw_tx_p"
    ]

    X_train = df_train[feature_cols]
    y_train = df_train['residual_target']
    X_test = df_test[feature_cols]
    y_test = df_test['residual_target']

    logger.info(f"Entraînement XGBoost sur {len(X_train)} échantillons...")

    model = xgb.XGBRegressor(
        tree_method="hist",
        n_estimators=500,
        learning_rate=0.05,
        max_depth=8,
        subsample=0.8,
        colsample_bytree=0.8,
        n_jobs=-1
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=100
    )

    # Correction 2 : Calcul de l'évaluation explicite (évite l'AttributeError sur best_score)
    preds_test = model.predict(X_test)
    rmse_test = np.sqrt(np.mean((y_test - preds_test) ** 2))

    # Sauvegarde du modèle compressé (< 100 Mo)
    model_path = Path(settings.model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path, compress=3)

    logger.info(f"Entraînement finalisé. Hold-out Test RMSE: {rmse_test:.4f} dB")
    logger.info(f"Modèle sauvegardé avec succès dans : {model_path}")

if __name__ == "__main__":
    train()