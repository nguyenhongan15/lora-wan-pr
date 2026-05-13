"""FastAPI server — POST /residual + GET /healthz.

Contract:
  POST /residual
    Headers: Authorization: Bearer <stage2_auth_token>
    Body:    Stage2Request (target + serving_gateway data, raw — server tự
             extract feature qua FeaturePipeline).
    Resp:    Stage2Response (residual_db, model_version) — or 503 nếu chưa
             active model.

Design choice: server tự build FeaturePipeline (DEM + OSM raster) thay vì
client (api-service) gửi 7 feature đã extract. Lý do:
  - DEM/OSM raster lớn (5.5 MB OSM + DEM ~30 MB), chỉ cần 1 copy trên
    ml-service-predict, api-service không gánh.
  - FeaturePipeline + Stage2 model implementation chi tiết là internal —
    api-service chỉ cần biết "đây là Target + Gateway, trả tôi residual".
    Đổi feature set không cần đổi api-service.

12F VI stateless: FeaturePipeline + Stage2 model load 1 lần ở lifespan startup;
mọi request đọc concurrent (booster + raster thread-safe read-only).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from lora_coverage_api.domain.coverage import Gateway, GatewayId, Target
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..features.dem import DemLookup
from ..features.extractor import FeaturePipeline
from ..features.osm import UrbanizationLookup
from ..registry.client import load_active
from ..stages.stage2_residual import Stage2ResidualModel
from ..training.guardrail import RESIDUAL_MAX_ABS_DB
from .ood import OODDetector

log = logging.getLogger(__name__)

# Pydantic DTOs — payload shape giữa api-service ↔ ml-service-predict.


class GatewayPayload(BaseModel):
    """Bare-minimum gateway fields cần cho feature extraction + Stage1.

    Tách khỏi Gateway domain class: api-service gửi qua JSON, không transmit
    UUID type info → string. Server convert string → GatewayId.
    """

    id: UUID
    code: str = ""
    name: str = ""
    latitude: float
    longitude: float
    altitude_m: float = 0.0
    antenna_height_m: float = 10.0
    antenna_gain_dbi: float = 2.0
    tx_power_dbm: float = 14.0
    frequency_mhz: float = 923.0


class TargetPayload(BaseModel):
    latitude: float
    longitude: float
    spreading_factor: int
    frequency_mhz: float = 923.0


class Stage2Request(BaseModel):
    """1 cặp (target, serving_gateway) → server extract feature + predict residual."""

    target: TargetPayload
    serving_gateway: GatewayPayload


class Stage2Response(BaseModel):
    """Response cho POST /residual.

    `residual_db` ĐÃ được clip về [-RESIDUAL_MAX_ABS_DB, +RESIDUAL_MAX_ABS_DB]
    nếu raw model output vượt threshold (guardrail layer 1).

    `ood` = True → feature ngoài bounding-box training → server trả
    residual_db=0 (Stage 1-only). Caller (api-service) KHÔNG cần fallback gì,
    cứ cộng vào Stage 1 như bình thường.

    `guardrail_violated` = True → raw |residual| > threshold (đã clip),
    api-service nên log để theo dõi model drift.
    """

    residual_db: float = Field(..., description="Cộng vào Stage1 RSSI để được Stage1+2 RSSI")
    model_version: str
    ood: bool = Field(False, description="True nếu feature ngoài training bounds")
    guardrail_violated: bool = Field(
        False, description="True nếu raw residual vượt threshold trước clip"
    )
    ood_features: list[str] = Field(
        default_factory=list, description="Tên feature vi phạm OOD bounds (nếu có)"
    )


class HealthResponse(BaseModel):
    status: str
    model_version: str | None
    has_stage2: bool


# ── Bearer token auth ────────────────────────────────────────────────────
_security = HTTPBearer(auto_error=False)


def _verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
    settings: Settings = Depends(get_settings),
) -> None:
    """401 nếu thiếu/sai bearer token. Q9: hardcoded admin token cho dev."""
    expected = settings.stage2_auth_token
    if credentials is None or credentials.credentials != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid stage2 bearer token",
        )


# ── Lifespan: load raster + Stage 2 model 1 lần khi startup ──────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info("Stage 2 server startup")

    dem = DemLookup(str(settings.dem_path))
    urb = UrbanizationLookup(str(settings.urbanization_path))
    candidates = _load_candidate_gateways(settings)
    pipeline = FeaturePipeline(
        candidate_gateways=candidates,
        dem_lookup=dem,
        urbanization_lookup=urb,
    )
    stage2: Stage2ResidualModel | None = load_active(settings)
    ood_detector: OODDetector | None = (
        OODDetector(stage2.feature_bounds) if stage2 and stage2.feature_bounds else None
    )

    app.state.pipeline = pipeline
    app.state.stage2 = stage2
    app.state.ood_detector = ood_detector
    app.state.settings = settings
    log.info(
        "Ready: candidates=%d stage2_loaded=%s ood_enabled=%s",
        len(candidates),
        stage2.model_version if stage2 else None,
        ood_detector is not None,
    )

    yield
    log.info("Stage 2 server shutdown")


def _load_candidate_gateways(settings: Settings) -> list[Gateway]:
    """All gateways trong bbox — cho FeaturePipeline.distance_to_2nd_nearest.

    Đọc lại từ DB mỗi lần startup (gateway list ít đổi; hot-reload khi cần).
    """
    query = """
    SELECT id, code, name,
           ST_Y(location::geometry) AS lat,
           ST_X(location::geometry) AS lon,
           altitude_m, antenna_height_m, antenna_gain_dbi, tx_power_dbm, frequency_mhz
    FROM geo.gateways
    """
    with psycopg.connect(settings.db_url) as conn, conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
    return [
        Gateway(
            id=GatewayId(r[0]),
            code=r[1],
            name=r[2],
            latitude=float(r[3]),
            longitude=float(r[4]),
            altitude_m=float(r[5]),
            antenna_height_m=float(r[6]),
            antenna_gain_dbi=float(r[7]),
            tx_power_dbm=float(r[8]),
            frequency_mhz=float(r[9]),
        )
        for r in rows
    ]


# ── FastAPI app ──────────────────────────────────────────────────────────
app = FastAPI(
    title="lora-ml-predict (Stage 2 serving)",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz", response_model=HealthResponse)
def healthz(request: Request) -> HealthResponse:
    """Unauth health probe (Docker compose healthcheck).

    KHÔNG bearer-protected: dùng cho liveness + readiness; expose chỉ
    boolean has_stage2 (không leak model_version nếu unauth — vẫn safe nội bộ).
    """
    stage2: Stage2ResidualModel | None = request.app.state.stage2
    return HealthResponse(
        status="ok",
        model_version=stage2.model_version if stage2 else None,
        has_stage2=stage2 is not None,
    )


@app.post(
    "/residual",
    response_model=Stage2Response,
    dependencies=[Depends(_verify_token)],
)
def residual(req: Stage2Request, request: Request) -> Stage2Response:
    """Extract feature + OOD check + Stage2 predict + guardrail clip.

    Pipeline:
      1. Extract FeatureVector qua FeaturePipeline (DEM + OSM + math).
      2. OOD check (nếu detector available): feature ngoài bounds → trả
         residual_db=0 (api-service tự cộng Stage 1).
      3. Predict residual → clip về [-RESIDUAL_MAX_ABS_DB, +RESIDUAL_MAX_ABS_DB]
         (guardrail layer 1). Set guardrail_violated flag nếu raw vượt.
      4. RSSI [-150, -30] clip là layer 2: do api-service apply (cần biết
         Stage 1 baseline mới combine được).

    503 khi chưa có active Stage 2 model → caller fallback Stage1 only.
    """
    stage2: Stage2ResidualModel | None = request.app.state.stage2
    if stage2 is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no active Stage 2 model",
        )

    pipeline: FeaturePipeline = request.app.state.pipeline
    ood_detector: OODDetector | None = request.app.state.ood_detector

    target = Target(
        latitude=req.target.latitude,
        longitude=req.target.longitude,
        spreading_factor=req.target.spreading_factor,
        frequency_mhz=req.target.frequency_mhz,
    )
    gateway = Gateway(
        id=GatewayId(req.serving_gateway.id),
        code=req.serving_gateway.code,
        name=req.serving_gateway.name,
        latitude=req.serving_gateway.latitude,
        longitude=req.serving_gateway.longitude,
        altitude_m=req.serving_gateway.altitude_m,
        antenna_height_m=req.serving_gateway.antenna_height_m,
        antenna_gain_dbi=req.serving_gateway.antenna_gain_dbi,
        tx_power_dbm=req.serving_gateway.tx_power_dbm,
        frequency_mhz=req.serving_gateway.frequency_mhz,
    )
    fv = pipeline.extract(target, gateway)

    if ood_detector is not None:
        ood_result = ood_detector.check(fv)
        if ood_result.is_ood:
            log.info(
                "OOD sample → Stage1-only fallback (violations=%s)",
                ood_result.violating_features,
            )
            return Stage2Response(
                residual_db=0.0,
                model_version=stage2.model_version,
                ood=True,
                guardrail_violated=False,
                ood_features=list(ood_result.violating_features),
            )

    raw_residual = stage2.predict_residual(fv)
    violated = abs(raw_residual) > RESIDUAL_MAX_ABS_DB
    if raw_residual > RESIDUAL_MAX_ABS_DB:
        residual_db = RESIDUAL_MAX_ABS_DB
    elif raw_residual < -RESIDUAL_MAX_ABS_DB:
        residual_db = -RESIDUAL_MAX_ABS_DB
    else:
        residual_db = raw_residual
    if violated:
        log.info(
            "Guardrail clip: raw=%.2f → %.2f dB",
            raw_residual,
            residual_db,
        )
    return Stage2Response(
        residual_db=residual_db,
        model_version=stage2.model_version,
        ood=False,
        guardrail_violated=bool(violated),
        ood_features=[],
    )
