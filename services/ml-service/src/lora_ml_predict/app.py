import logging
import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import joblib
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# CRITICAL: phải khớp với scripts/train_residual_model.py:TRAINING_FEATURE_COLS.
# Đổi feature set yêu cầu retrain model + cập nhật cả hai nơi.
TRAINING_FEATURE_COLS = [
    "lat",
    "lon",
    "sf",
    "gw_lat",
    "gw_lon",
    "distance_km",
    "log_distance_km",
    "delta_alt_m",
]

# --- Config ---


class Settings(BaseSettings):
    auth_token: str = Field(alias="LORA_STAGE2_AUTH_TOKEN")
    db_url: str = Field(alias="LORA_DB_URL")
    port: int = 8001
    host: str = "0.0.0.0"
    model_version: str = "stage2-xgb-v0.6.0"
    model_path: str = Field(alias="LORA_ML_MODEL_PATH")

    # OOD Constraints (Vietnam, AS923-2)
    min_lat: float = 8.4
    max_lat: float = 23.4
    min_lon: float = 102.1
    max_lon: float = 109.5
    min_sf: int = 7
    max_sf: int = 12
    min_freq_mhz: float = 921.4
    max_freq_mhz: float = 924.8

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model = None
    app.state.is_model_active = False  # État stocké de manière thread-safe dans l'app

    if Path(settings.model_path).exists():
        try:
            app.state.model = joblib.load(settings.model_path)
            app.state.is_model_active = True
            logger.info(f"Model loaded from {settings.model_path}")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            app.state.is_model_active = False
    else:
        logger.warning(f"Model artifact not found at {settings.model_path}. Service inactive.")
        app.state.is_model_active = False
    yield
    app.state.model = None
    app.state.is_model_active = False


# --- App Schemas ---

app = FastAPI(title="LoRa ML Prediction Service", lifespan=lifespan)
security = HTTPBearer(auto_error=False)


class TargetSchema(BaseModel):
    latitude: float
    longitude: float
    spreading_factor: int
    frequency_mhz: float


class BatchTargetSchema(TargetSchema):
    stage1_pl_db: float | None = None


class GatewaySchema(BaseModel):
    id: str
    code: str
    name: str
    latitude: float
    longitude: float
    altitude_m: float
    antenna_height_m: float
    antenna_gain_dbi: float
    tx_power_dbm: float
    frequency_mhz: float


class PredictionRequest(BaseModel):
    target: TargetSchema
    serving_gateway: GatewaySchema


class PredictionResponse(BaseModel):
    residual_db: float | None
    model_version: str
    ood: bool = False


class BatchPredictionRequest(BaseModel):
    gateway: GatewaySchema
    targets: list[BatchTargetSchema]


class BatchResidualItem(BaseModel):
    residual_db: float | None
    ood: bool


class BatchPredictionResponse(BaseModel):
    model_version: str
    residuals: list[BatchResidualItem]


# --- Helpers & Dependencies ---


async def verify_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
):
    if credentials is None or credentials.credentials != settings.auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def check_model_active(request: Request):
    # Lecture dynamique de l'état réel de l'application
    if not getattr(request.app.state, "is_model_active", False):
        raise HTTPException(status_code=503, detail="no active model")


def is_ood(lat: float, lon: float, sf: int, freq: float) -> bool:
    return not (
        settings.min_lat <= lat <= settings.max_lat
        and settings.min_lon <= lon <= settings.max_lon
        and settings.min_sf <= sf <= settings.max_sf
        and settings.min_freq_mhz <= freq <= settings.max_freq_mhz
    )


def extract_features_dict(t: TargetSchema, gw: GatewaySchema) -> dict:
    """Build 8-feature row khớp TRAINING_FEATURE_COLS (v0.5+).

    Derived columns (distance_km, log_distance_km, delta_alt_m) tính tại đây
    để model.predict nhận đúng schema. Công thức phải khớp
    scripts/train_residual_model.py:_add_derived.
    """
    lat1, lon1 = math.radians(t.latitude), math.radians(t.longitude)
    lat2, lon2 = math.radians(gw.latitude), math.radians(gw.longitude)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    distance_km = 2 * 6371.0088 * math.asin(math.sqrt(min(a, 1.0)))
    return {
        "lat": t.latitude,
        "lon": t.longitude,
        "sf": float(t.spreading_factor),
        "gw_lat": gw.latitude,
        "gw_lon": gw.longitude,
        "distance_km": distance_km,
        "log_distance_km": math.log1p(distance_km),
        "delta_alt_m": gw.altitude_m + gw.antenna_height_m,
    }


# --- API Endpoints ---


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/residual", response_model=PredictionResponse)
async def predict_residual(
    request: Request,
    payload: PredictionRequest,
    _auth: Annotated[None, Depends(verify_token)],
    _active: Annotated[None, Depends(check_model_active)],
):
    t = payload.target
    if is_ood(t.latitude, t.longitude, t.spreading_factor, t.frequency_mhz):
        return PredictionResponse(residual_db=None, model_version=settings.model_version, ood=True)

    features = pd.DataFrame([extract_features_dict(t, payload.serving_gateway)])[
        TRAINING_FEATURE_COLS
    ]

    try:
        residual = float(request.app.state.model.predict(features)[0])
        return PredictionResponse(
            residual_db=residual, model_version=settings.model_version, ood=False
        )
    except Exception as e:
        logger.error(f"Inference error: {e}")
        raise HTTPException(status_code=500, detail="Internal inference error") from e


@app.post("/residuals/batch", response_model=BatchPredictionResponse)
async def predict_residuals_batch(
    request: Request,
    payload: BatchPredictionRequest,
    _auth: Annotated[None, Depends(verify_token)],
    _active: Annotated[None, Depends(check_model_active)],
):
    gw = payload.gateway
    targets = payload.targets

    if len(targets) > 5000:
        logger.warning(f"Batch request size ({len(targets)}) exceeds recommended limit.")

    results = []
    rows_to_predict = []
    map_indices = []

    for idx, t in enumerate(targets):
        if is_ood(t.latitude, t.longitude, t.spreading_factor, t.frequency_mhz):
            results.append(BatchResidualItem(residual_db=None, ood=True))
        else:
            results.append(None)
            rows_to_predict.append(extract_features_dict(t, gw))
            map_indices.append(idx)

    if rows_to_predict:
        try:
            df_batch = pd.DataFrame(rows_to_predict)[TRAINING_FEATURE_COLS]
            preds = request.app.state.model.predict(df_batch)
            for i, pred in enumerate(preds):
                results[map_indices[i]] = BatchResidualItem(residual_db=float(pred), ood=False)
        except Exception as e:
            logger.error(f"Batch inference error: {e}")
            raise HTTPException(status_code=500, detail="Internal batch inference error") from e

    return BatchPredictionResponse(model_version=settings.model_version, residuals=results)


def main() -> None:
    """Entry point cho `python -m lora_ml_predict.app` và pyproject script."""
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
