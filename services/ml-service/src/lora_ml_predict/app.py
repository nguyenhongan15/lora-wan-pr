import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import joblib
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .processing import compute_link_features

# Extra Trees feature set — phải khớp services/ml-service/scripts/train_extra_trees.py.
# Pipeline (ColumnTransformer + ExtraTreesRegressor) đã encode `gateway`
# bằng OneHotEncoder nên list này feed thẳng vào model.predict.
_NUMERIC_FEATURES = [
    "frequency",
    "spreading_factor",
    "log_distance",
    "log_distance_3d",
    "delta_lat",
    "delta_lon",
    "angle",
    "gw_elevation",
    "delta_elevation",
    "elevation_angle",
    "slope",
    "roughness",
    "terrain_mean",
    "terrain_std",
    "terrain_min",
    "terrain_max",
    "fresnel_obstruction_ratio",
    "min_fresnel_clearance",
    "mean_fresnel_clearance",
    "residential_ratio",
]
_ALL_FEATURES = [*_NUMERIC_FEATURES, "gateway"]

# Cột P.1812 RSSI khi physics-as-feature (build_training_csv --with-stage1-rssi).
_STAGE1_COL = "stage1_rssi_dbm"

# Meta mặc định khi thiếu model_meta.json (model absolute cũ — backward compat):
# output = RSSI tuyệt đối → residual = output - stage1_rssi.
_DEFAULT_MODEL_META: dict = {
    "target_kind": "absolute",
    "all_features": _ALL_FEATURES,
    "with_stage1_feature": False,
}

# --- Config ---


class Settings(BaseSettings):
    auth_token: str = Field(alias="LORA_STAGE2_AUTH_TOKEN")
    db_url: str = Field(alias="LORA_DB_URL")
    port: int = 8001
    host: str = "0.0.0.0"
    model_version: str = "stage2-et-v0.7.0"
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


def _load_holdout_mse_db2() -> float | None:
    """Đọc val_metrics.json (cạnh model artifact) → MSE holdout = rmse².

    Dùng làm thành phần epistemic uncertainty trả về /residual: api-service cộng
    vào confidence để dải ±σ trên UI phản ánh đúng sai số model (~7 dB), thay vì
    chỉ shadow-fading. None nếu thiếu file/giá trị bất thường.
    """
    val_path = Path(settings.model_path).parent / "val_metrics.json"
    if not val_path.exists():
        return None
    try:
        rmse = json.loads(val_path.read_text()).get("rmse")
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to read val_metrics.json: {e}")
        return None
    if isinstance(rmse, (int, float)) and rmse > 0:
        return float(rmse) ** 2
    return None


def _load_model_meta() -> dict:
    """Đọc model_meta.json (cạnh artifact) → cách diễn giải output model.

    Keys: target_kind ('absolute'|'residual'), all_features (list), with_stage1_feature.
    Thiếu file → _DEFAULT_MODEL_META (model absolute cũ): output là RSSI tuyệt đối
    nên residual = output - stage1_rssi (giữ hành vi backward-compat).
    """
    meta_path = Path(settings.model_path).parent / "model_meta.json"
    if not meta_path.exists():
        return dict(_DEFAULT_MODEL_META)
    try:
        raw = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to read model_meta.json: {e} — dùng default absolute")
        return dict(_DEFAULT_MODEL_META)
    return {
        "target_kind": raw.get("target_kind", "absolute"),
        "all_features": raw.get("all_features", _ALL_FEATURES),
        "with_stage1_feature": bool(raw.get("with_stage1_feature", False)),
    }


def _model_output_to_residual(model_output: float, stage1_rssi_dbm: float, meta: dict) -> float:
    """Quy đổi output model -> residual_db = (RSSI cuối) - stage1.

    - residual model: output ĐÃ là residual -> trả thẳng.
    - absolute model: output là RSSI tuyệt đối -> residual = output - stage1.
    api-service luôn cộng lại: final = stage1 + residual => fusion vật lý + ML.
    """
    if meta.get("target_kind") == "residual":
        return model_output
    return model_output - stage1_rssi_dbm


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model = None
    app.state.is_model_active = False  # État stocké de manière thread-safe dans l'app
    app.state.holdout_mse_db2 = None
    app.state.model_meta = dict(_DEFAULT_MODEL_META)

    if Path(settings.model_path).exists():
        try:
            app.state.model = joblib.load(settings.model_path)
            app.state.is_model_active = True
            app.state.holdout_mse_db2 = _load_holdout_mse_db2()
            app.state.model_meta = _load_model_meta()
            logger.info(
                f"Model loaded from {settings.model_path} "
                f"(target_kind={app.state.model_meta['target_kind']})"
            )
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
    # ET dự đoán RSSI tuyệt đối; endpoint trả `residual_db = rssi_et −
    # stage1_rssi_dbm` để api-service cộng lại RSSI cuối. None → không tính
    # được delta, trả None + ood=False để caller fallback Stage 1.
    stage1_rssi_dbm: float | None = None


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
    # MSE holdout (dB²) của model — epistemic uncertainty để api-service dựng dải
    # ±σ trung thực. None khi không đọc được val_metrics.
    holdout_mse_db2: float | None = None


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


def extract_features_dict(t: TargetSchema, gw: GatewaySchema) -> dict | None:
    """Build 20-numeric + gateway feature row khớp ExtraTreesRegressor pipeline.

    Gọi `compute_link_features` (port của reference_wireless/src/processing)
    để DEM + OSM lookup + Fresnel/landuse stats. Return None khi DEM lookup
    fail ở cả 2 endpoint (compute_link_features filter row out).

    Antenna heights lấy từ DB (gateway.antenna_height_m); device_ant_h_m mặc
    định 1.5m khớp training.
    """
    return compute_link_features(
        lat=t.latitude,
        lon=t.longitude,
        gw_lat=gw.latitude,
        gw_lon=gw.longitude,
        gw_ant_h_m=gw.antenna_height_m,
        freq_hz=gw.frequency_mhz * 1e6,
        sf=t.spreading_factor,
        gateway_code=gw.code,
    )


# --- API Endpoints ---


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/admin/reload")
async def admin_reload(
    request: Request,
    _auth: Annotated[None, Depends(verify_token)],
):
    """Hot-reload joblib model. Goi sau khi Celery retrain_ml_model atomic-swap
    file artifact xong — tranh phai docker restart ml-service.

    Cung bearer token nhu /residual (LORA_STAGE2_AUTH_TOKEN).
    """
    path = Path(settings.model_path)
    if not path.exists():
        request.app.state.model = None
        request.app.state.is_model_active = False
        raise HTTPException(
            status_code=503,
            detail=f"Model artifact not found at {settings.model_path}",
        )
    try:
        # joblib.load là blocking I/O + CPU deserialize (~10-15s cho 122MB
        # Extra Trees 1500-tree). Chạy trong thread để không block event loop
        # — /healthz + /residual vẫn responsive trong khi reload.
        request.app.state.model = await asyncio.to_thread(joblib.load, path)
        request.app.state.is_model_active = True
        request.app.state.holdout_mse_db2 = _load_holdout_mse_db2()
        request.app.state.model_meta = _load_model_meta()
        logger.info(
            f"Model hot-reloaded from {settings.model_path} "
            f"(target_kind={request.app.state.model_meta['target_kind']})"
        )
        return {"status": "ok", "model_path": str(path), "model_version": settings.model_version}
    except Exception as e:
        request.app.state.is_model_active = False
        logger.error(f"Failed to hot-reload model: {e}")
        raise HTTPException(status_code=500, detail=f"reload failed: {e}") from e


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

    if t.stage1_rssi_dbm is None:
        logger.warning(
            "/residual called without stage1_rssi_dbm; cannot convert ET output to residual"
        )
        return PredictionResponse(residual_db=None, model_version=settings.model_version, ood=False)

    feats = extract_features_dict(t, payload.serving_gateway)
    if feats is None:
        logger.warning(
            "Feature extraction failed (DEM lookup) for (%s, %s)", t.latitude, t.longitude
        )
        return PredictionResponse(residual_db=None, model_version=settings.model_version, ood=False)

    meta = getattr(request.app.state, "model_meta", _DEFAULT_MODEL_META)
    if meta.get("with_stage1_feature"):
        feats = {**feats, _STAGE1_COL: t.stage1_rssi_dbm}
    features = pd.DataFrame([feats])[meta.get("all_features", _ALL_FEATURES)]
    try:
        model_out = float(request.app.state.model.predict(features)[0])
        residual = _model_output_to_residual(model_out, t.stage1_rssi_dbm, meta)
        return PredictionResponse(
            residual_db=residual,
            model_version=settings.model_version,
            ood=False,
            holdout_mse_db2=getattr(request.app.state, "holdout_mse_db2", None),
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

    results: list[BatchResidualItem | None] = []
    rows_to_predict: list[dict] = []
    stage1_rssi_per_row: list[float] = []
    map_indices: list[int] = []

    for idx, t in enumerate(targets):
        if is_ood(t.latitude, t.longitude, t.spreading_factor, t.frequency_mhz):
            results.append(BatchResidualItem(residual_db=None, ood=True))
            continue
        if t.stage1_rssi_dbm is None:
            results.append(BatchResidualItem(residual_db=None, ood=False))
            continue
        feats = extract_features_dict(t, gw)
        if feats is None:
            results.append(BatchResidualItem(residual_db=None, ood=False))
            continue
        results.append(None)
        rows_to_predict.append(feats)
        stage1_rssi_per_row.append(t.stage1_rssi_dbm)
        map_indices.append(idx)

    if rows_to_predict:
        meta = getattr(request.app.state, "model_meta", _DEFAULT_MODEL_META)
        if meta.get("with_stage1_feature"):
            for row, s1 in zip(rows_to_predict, stage1_rssi_per_row, strict=True):
                row[_STAGE1_COL] = s1
        try:
            df_batch = pd.DataFrame(rows_to_predict)[meta.get("all_features", _ALL_FEATURES)]
            preds = request.app.state.model.predict(df_batch)
            for i, model_out in enumerate(preds):
                residual = _model_output_to_residual(float(model_out), stage1_rssi_per_row[i], meta)
                results[map_indices[i]] = BatchResidualItem(residual_db=residual, ood=False)
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
