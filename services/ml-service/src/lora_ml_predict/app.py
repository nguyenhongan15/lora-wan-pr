import os
import logging
from typing import Annotated
from contextlib import asynccontextmanager
#from urllib.request import Request

from fastapi import FastAPI, Depends, HTTPException, status, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Config ---

class Settings(BaseSettings):
    auth_token: str = Field(alias="LORA_STAGE2_AUTH_TOKEN")
    port: int = 8001
    host: str = "0.0.0.0"
    model_version: str = "stage2-stub-v0.1.0"
    # Set to False to simulate "no active model" (503)
    is_model_active: bool = True
    model_path: str | None = Field(default=None, alias="LORA_ML_MODEL_PATH")
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Placeholder for the loaded model
model_artifact = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialisation de l'état
    app.state.model = None
    
    logger.info("ML service starting up...")
    
    if settings.model_path and os.path.exists(settings.model_path):
        try:
            logger.info(f"Loading model from {settings.model_path}")
            # Simulation du chargement
            
            settings.is_model_active = True
            app.state.model = "MOCK_MODEL_DATA" 
            logger.info("Model loaded successfully")
        except Exception as e:
            settings.is_model_active = False
            logger.error(f"Failed to load: {e}")
    else:
        settings.is_model_active = False
        logger.warning("No model path configured or file not found. Service will return 503.")

    yield
    # Nettoyage
    app.state.model = None

# --- App ---

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
    residual_db: float
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

async def verify_token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]):
    if credentials is None or credentials.credentials != settings.auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )

def check_model_active():
    if not settings.is_model_active:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no active model"
        )

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.post("/residual", response_model=PredictionResponse)
async def predict_residual(
    request: Request,
    payload: PredictionRequest,
    _auth: Annotated[None, Depends(verify_token)],
    _active: Annotated[None, Depends(check_model_active)]
):
    """
    POST /residual — per-target, used by point-prediction via api-service.
    """
    # Accès au modèle via l'état de l'application
    model = request.app.state.model
    
    # Placeholder: Ici tu utiliseras ton objet 'model' pour l'inférence
    return PredictionResponse(
        residual_db=0.0,
        model_version=settings.model_version,
        ood=False
    )

@app.post("/residuals/batch", response_model=BatchPredictionResponse)
async def predict_residuals_batch(
    request: Request,
    payload: BatchPredictionRequest, # Renommé pour cohérence
    _auth: Annotated[None, Depends(verify_token)],
    _active: Annotated[None, Depends(check_model_active)]
):
    """
    POST /residuals/batch — bulk, for min-SF precompute.
    """
    # Accès au modèle via l'état de l'application
    model = request.app.state.model

    # Batch size limit check
    if len(payload.targets) > 5000:
        logger.warning("Batch size too large: %d", len(payload.targets))

    # Placeholder logic
    residuals = [
        BatchResidualItem(residual_db=0.0, ood=False)
        for _ in payload.targets
    ]
    
    return BatchPredictionResponse(
        model_version=settings.model_version,
        residuals=residuals
    )

def main():
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)

if __name__ == "__main__":
    main()
