"""
schemas.py — Toàn bộ Pydantic request/response schemas.

Tất cả response model kế thừa CamelModel → tự động chuyển
snake_case Python → camelCase JSON (tuân thủ API Contract).

Ví dụ: field `rssi_dbm` sẽ serialize ra `rssiDbm` trong JSON response.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import Field, UUID4

from core.responses import CamelModel

from typing import Any
from pydantic import model_validator


# ─────────────────────────────────────────────
# Gateway
# ─────────────────────────────────────────────

class GatewayOut(CamelModel):
    id:               UUID4
    name:             Optional[str] = None
    gateway_eui:      str
    altitude_m:       Optional[float] = None
    antenna_height_m: Optional[float] = None
    tx_power_dbm:     Optional[float] = None
    antenna_type:     Optional[str] = None
    longitude:        Optional[float] = None
    latitude:         Optional[float] = None
    installed_at:     Optional[datetime] = None


# ─────────────────────────────────────────────
# Campaign
# ─────────────────────────────────────────────

class CampaignOut(CamelModel):
    id:                UUID4
    name:              str
    environment_type:  Optional[str] = None
    start_date:        Optional[str] = None
    end_date:          Optional[str] = None
    weather_condition: Optional[str] = None


# ─────────────────────────────────────────────
# Measurement
# ─────────────────────────────────────────────

class MeasurementOut(CamelModel):
    id:               UUID4
    rssi_dbm:         float
    snr_db:           Optional[float] = None
    spreading_factor: Optional[int] = None
    measured_at:      datetime
    longitude:        Optional[float] = None
    latitude:         Optional[float] = None
    gateway_id:       UUID4


# ─────────────────────────────────────────────
# ML Model metadata
# ─────────────────────────────────────────────

class MlModelOut(CamelModel):
    id:                 UUID4
    name:               str
    algorithm:          Optional[str] = None
    version:            Optional[str] = None
    rmse_db:            Optional[float] = None
    mae_db:             Optional[float] = None
    r2_score:           Optional[float] = None
    hyperparameters:    Optional[dict] = None
    feature_importance: Optional[dict] = None
    trained_at:         Optional[datetime] = None


# ─────────────────────────────────────────────
# Train endpoint I/O
# ─────────────────────────────────────────────

class TrainRequest(CamelModel):
    algorithm: Literal["xgboost", "random_forest", "gaussian_process"] = Field(
        "xgboost",
        description="Thuật toán ML cần train",
    )
    hyperparameters: Optional[dict] = Field(
        None,
        description="Override hyperparameters mặc định của model",
    )
    n_cv_splits:      int = Field(5, ge=0, le=10)
    min_measurements: int = Field(30, ge=10)
    spreading_factor: Optional[int]   = Field(None, ge=7, le=12)
    freq_mhz:         Optional[float] = Field(None, ge=400.0, le=1000.0)


class TrainResponse(CamelModel):
    model_id:           str
    algorithm:          str
    n_samples:          int
    metrics:            dict
    feature_importance: dict
    trained_at:         str
    message:            str


# ─────────────────────────────────────────────
# Run (interpolation / ML predict) I/O
# ─────────────────────────────────────────────

class RunRequest(CamelModel):
    algorithm: Literal[
        "idw", "kriging", "rbf", "delaunay",
        "xgboost", "random_forest", "gaussian_process"
    ] = Field(
        "idw",
        description="Phương pháp nội suy (idw/kriging/rbf/delaunay) hoặc ML predict",
    )
    grid_resolution_m: int   = Field(50, ge=10, le=500)

    # IDW
    idw_power:         float = Field(2.0, ge=0.5, le=5.0)
    idw_neighbors:     int   = Field(12, ge=3, le=50)

    # Kriging
    kriging_model: Literal["spherical", "gaussian", "exponential"] = "spherical"

    # RBF — kernel và smoothing
    rbf_function: Literal[
        "linear", "thin_plate_spline", "multiquadric",
        "inverse_multiquadric", "gaussian", "cubic",
    ] = Field(
        "linear",
        description=(
            "RBF kernel: 'linear' (mặc định, ổn định), "
            "'thin_plate_spline' (mượt), 'multiquadric' (cong), "
            "'gaussian' (smooth decay)"
        ),
    )
    rbf_smoothing: float = Field(
        0.0, ge=0.0, le=50.0,
        description="Smoothing factor cho RBF (0=nội suy chính xác, >0=làm mượt noise)",
    )
    rbf_anchoring: bool = Field(
        True,
        description="Thêm corner anchor points để tránh extrapolation bùng nổ tại biên",
    )

    # Delaunay
    delaunay_method: Literal["linear", "cubic"] = Field(
        "linear",
        description="'linear' (nhanh, C0) hoặc 'cubic' (mượt hơn, C1, chậm hơn)",
    )
    delaunay_fill: bool = Field(
        True,
        description="Fill vùng ngoài convex hull bằng nearest-neighbor (không có lỗ trên map)",
    )

    # ML
    ml_model_id: Optional[str] = Field(
        None,
        description="model_id từ /predict/train — bắt buộc khi dùng xgboost/rf/gp",
    )
    min_measurements: int = Field(30, ge=5)


class RunResponse(CamelModel):
    campaign_id:  str
    algorithm:    str
    grid_points:  int
    model_db_id:  str
    duration_sec: float
    message:      str


# ─────────────────────────────────────────────
# Pagination params (dùng ở list endpoints)
# ─────────────────────────────────────────────

class PageParams(CamelModel):
    page:  int = Field(1,  ge=1)
    limit: int = Field(20, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit

# ═════════════════════════════════════════════
# AOI (Phase 8)
# ═════════════════════════════════════════════
 
class AOISummary(CamelModel):
    """List item — không kèm boundary geojson."""
    id:               UUID4
    slug:             str
    name:             str
    admin_level:      Optional[int]   = None
    osm_relation_id:  Optional[int]   = None
    area_km2:         Optional[float] = None
    polygon_count:    int
 
 
class AOIDetail(AOISummary):
    """Detail kèm boundary GeoJSON + bbox cho map."""
    boundary: dict       # GeoJSON Geometry
    bbox:     list[float]  # [minLng, minLat, maxLng, maxLat]
 
 
class CandidateSummary(CamelModel):
    id:        UUID4
    h3_index:  str
    lat:       float
    lng:       float
    cost:      float
    source:    Literal["grid", "infra"]
 
 
# ═════════════════════════════════════════════
# Optimization (Phase 8)
# ═════════════════════════════════════════════
 
class CoverageConfigInput(CamelModel):
    """Path loss + coverage params cho POST /optimization-runs."""
    model:                  Literal["hata", "log_distance", "longley-rice"] = "hata"
    frequency_mhz:          float = Field(923.0, gt=0, le=10_000)
    sf:                     int   = Field(10, ge=7, le=12)
    tx_power_dbm:           float = Field(17.0, ge=-10, le=30)
    tx_antenna_height_m:    float = Field(30.0, ge=1, le=200)
    rx_antenna_height_m:    float = Field(1.5, ge=0.5, le=10)
    tx_antenna_gain_dbi:    float = Field(3.0, ge=0, le=30)
    rx_antenna_gain_dbi:    float = Field(2.0, ge=0, le=30)
    r_max_m:                float = Field(20_000.0, gt=0, le=50_000)
    min_coverage_prob:      float = Field(0.5, gt=0, lt=1)
 
 
class OptimizationRunCreate(CamelModel):
    """Body cho POST /optimization-runs."""
    aoi_slug:         str  = Field(..., min_length=1, max_length=64)
    urban_slug:       Optional[str] = Field(None, max_length=64)
    mode:             Literal["mclp", "lscp"]
    k_max:            Optional[int]   = Field(None, gt=0, le=500)
    target_coverage:  Optional[float] = Field(None, gt=0, le=1)
    cost_aware:       bool = True
    coverage_config:  CoverageConfigInput
    k_safety_max:     int  = Field(50, gt=0, le=500)
    notes:            Optional[str]   = Field(None, max_length=500)
 
    @model_validator(mode="after")
    def _check_mode_params(self) -> "OptimizationRunCreate":
        if self.mode == "mclp" and self.k_max is None:
            raise ValueError("k_max bắt buộc khi mode='mclp'")
        if self.mode == "lscp" and self.target_coverage is None:
            raise ValueError("target_coverage bắt buộc khi mode='lscp'")
        return self
 
 
class SelectionDetailOutput(CamelModel):
    rank:           int
    candidate_id:   str
    h3_index:       Optional[str]   = None
    lat:            Optional[float] = None
    lng:            Optional[float] = None
    cost:           float
    source:         Optional[str]   = None
    marginal_gain:  float
 
 
class OptimizationRunSummary(CamelModel):
    id:                    UUID4
    mode:                  Literal["mclp", "lscp"]
    k_max:                 Optional[int]   = None
    target_coverage:       Optional[float] = None
    cost_aware:            bool
    coverage_config_hash:  str
    n_selected:            int
    coverage_ratio:        float
    total_cost:            float
    compute_ms:            int
    correlation_id:        Optional[str]   = None
    notes:                 Optional[str]   = None
    created_at:            datetime
    warnings:              list[str] = Field(default_factory=list)
 
 
class OptimizationRunDetail(OptimizationRunSummary):
    aoi_id:             UUID4
    coverage_config:    dict
    selection_details:  list[SelectionDetailOutput]
    total_coverage_w:   float
    n_iterations:       int
    updated_at:         datetime
 