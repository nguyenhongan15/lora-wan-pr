import os
import logging
from typing import Annotated

from fastapi import FastAPI, Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Config ---

class Settings(BaseSettings):
    auth_token: str = Field(alias="LORA_STAGE2_AUTH_TOKEN")
    port: int = 8001
    host: str = "0.0.0.0"
    model_version: str = "stage2-stub-v0.1.0"
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- App ---

app = FastAPI(title="LoRa ML Prediction Service")
security = HTTPBearer()

class TargetSchema(BaseModel):
    latitude: float
    longitude: float
    spreading_factor: int
    frequency_mhz: float

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

async def verify_token(credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]):
    if credentials.credentials != settings.auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.post("/residual", response_model=PredictionResponse)
async def predict_residual(
    request: PredictionRequest,
    _auth: Annotated[None, Depends(verify_token)]
):
    """
    Placeholder for Stage 2 residual prediction.
    In a real implementation, this would load a model and features.
    """
    # For now, return a 0.0 residual (no correction)
    return PredictionResponse(
        residual_db=0.0,
        model_version=settings.model_version
    )

def main():
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)

if __name__ == "__main__":
    main()
