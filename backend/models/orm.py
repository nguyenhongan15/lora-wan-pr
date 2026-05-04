"""
models/orm.py — SQLAlchemy ORM đồng bộ với db/init/01_schema.sql.

Tuân thủ rulefordesigndatabase.pdf:
  - Mục 1: Naming — bảng plural (projects, gateways...), PK = id, FK = <singular>_id
           Constraint names: pk_<table>, fk_<table>_<ref>, uq_<table>_<col>
  - Mục 2: NOT NULL tối đa, TIMESTAMPTZ cho thời gian
  - Mục 4: Index đầy đủ FK + composite + partial (cho soft-delete)
  - Mục 5: Audit trails created_at/updated_at/deleted_at ở bảng nghiệp vụ
  - Mục 6: UUID v4

LƯU Ý tên bảng: `__tablename__` đổi sang plural để khớp với SQL mới.
"""

from __future__ import annotations

import uuid

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from database import Base


# ─────────────────────────────────────────────────────────────
# projects
# ─────────────────────────────────────────────────────────────
class Project(Base):
    __tablename__ = "projects"

    id           = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    name         = Column(String(255), nullable=False)
    description  = Column(Text)
    organization = Column(String(255))

    # Audit trails
    created_at   = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at   = Column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_projects"),
    )


# ─────────────────────────────────────────────────────────────
# gateways
# ─────────────────────────────────────────────────────────────
class Gateway(Base):
    __tablename__ = "gateways"

    id               = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    project_id       = Column(UUID(as_uuid=True),
                              ForeignKey("projects.id", ondelete="CASCADE",
                                         name="fk_gateways_projects"),
                              nullable=False)
    gateway_eui      = Column(String(16), nullable=False)
    name             = Column(String(255))
    location         = Column(Geometry("POINT", srid=4326))
    altitude_m       = Column(Float)
    antenna_height_m = Column(Float)
    tx_power_dbm     = Column(Float)
    antenna_type     = Column(String(100))
    installed_at     = Column(DateTime(timezone=True))

    created_at       = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at       = Column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_gateways"),
        UniqueConstraint("gateway_eui", name="uq_gateways_gateway_eui"),
        CheckConstraint(r"gateway_eui ~ '^[0-9a-f]{16}$'",
                        name="ck_gateways_gateway_eui"),
        Index("idx_gateways_project_id", "project_id"),
        Index("idx_gateways_location", "location", postgresql_using="gist"),
        Index("idx_gateways_active_by_project", "project_id",
              postgresql_where="deleted_at IS NULL"),
    )


# ─────────────────────────────────────────────────────────────
# devices
# ─────────────────────────────────────────────────────────────
class Device(Base):
    __tablename__ = "devices"

    id          = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    project_id  = Column(UUID(as_uuid=True),
                         ForeignKey("projects.id", ondelete="CASCADE",
                                    name="fk_devices_projects"),
                         nullable=False)
    dev_eui     = Column(String(16), nullable=False)
    name        = Column(String(255))
    device_type = Column(String(100))

    created_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at  = Column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_devices"),
        UniqueConstraint("dev_eui", name="uq_devices_dev_eui"),
        CheckConstraint(r"dev_eui ~ '^[0-9a-f]{16}$'",
                        name="ck_devices_dev_eui"),
        Index("idx_devices_project_id", "project_id"),
        Index("idx_devices_active_by_project", "project_id",
              postgresql_where="deleted_at IS NULL"),
    )


# ─────────────────────────────────────────────────────────────
# campaigns
# ─────────────────────────────────────────────────────────────
class Campaign(Base):
    __tablename__ = "campaigns"

    id                = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    project_id        = Column(UUID(as_uuid=True),
                               ForeignKey("projects.id", ondelete="CASCADE",
                                          name="fk_campaigns_projects"),
                               nullable=False)
    name              = Column(String(255), nullable=False)
    environment_type  = Column(String(50))
    start_date        = Column(Date)
    end_date          = Column(Date)
    equipment_notes   = Column(Text)
    weather_condition = Column(String(50))

    created_at        = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at        = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at        = Column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_campaigns"),
        CheckConstraint(
            "environment_type IS NULL OR environment_type IN "
            "('urban', 'suburban', 'rural', 'forest', 'coastal', 'mountain')",
            name="ck_campaigns_env_type",
        ),
        CheckConstraint(
            "weather_condition IS NULL OR weather_condition IN "
            "('clear', 'cloudy', 'rainy', 'foggy', 'stormy')",
            name="ck_campaigns_weather",
        ),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="ck_campaigns_date_range",
        ),
        Index("idx_campaigns_project_id", "project_id"),
        Index("idx_campaigns_active_by_project", "project_id",
              postgresql_where="deleted_at IS NULL"),
    )


# ─────────────────────────────────────────────────────────────
# environment_zones (master data — không cần deleted_at)
# ─────────────────────────────────────────────────────────────
class EnvironmentZone(Base):
    __tablename__ = "environment_zones"

    id                    = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    boundary              = Column(Geometry("POLYGON", srid=4326), nullable=False)
    zone_type             = Column(String(50))
    building_density      = Column(Float)
    avg_building_height_m = Column(Float)
    ndvi                  = Column(Float)
    land_use              = Column(String(50))

    created_at            = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at            = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_environment_zones"),
        CheckConstraint(
            "building_density IS NULL OR "
            "(building_density >= 0 AND building_density <= 1)",
            name="ck_environment_zones_building_density",
        ),
        CheckConstraint(
            "ndvi IS NULL OR (ndvi >= -1 AND ndvi <= 1)",
            name="ck_environment_zones_ndvi",
        ),
        Index("idx_environment_zones_boundary", "boundary", postgresql_using="gist"),
    )


# ─────────────────────────────────────────────────────────────
# campaign_zones (junction, 3NF)
# ─────────────────────────────────────────────────────────────
class CampaignZone(Base):
    __tablename__ = "campaign_zones"

    id          = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    campaign_id = Column(UUID(as_uuid=True),
                         ForeignKey("campaigns.id", ondelete="CASCADE",
                                    name="fk_campaign_zones_campaigns"),
                         nullable=False)
    zone_id     = Column(UUID(as_uuid=True),
                         ForeignKey("environment_zones.id", ondelete="CASCADE",
                                    name="fk_campaign_zones_environment_zones"),
                         nullable=False)
    created_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_campaign_zones"),
        UniqueConstraint("campaign_id", "zone_id",
                         name="uq_campaign_zones_campaign_zone"),
        Index("idx_campaign_zones_campaign_id", "campaign_id"),
        Index("idx_campaign_zones_zone_id", "zone_id"),
    )


# ─────────────────────────────────────────────────────────────
# measurements — bảng CORE
# ─────────────────────────────────────────────────────────────
class Measurement(Base):
    __tablename__ = "measurements"

    id               = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    gateway_id       = Column(UUID(as_uuid=True),
                              ForeignKey("gateways.id", name="fk_measurements_gateways"),
                              nullable=False)
    campaign_id      = Column(UUID(as_uuid=True),
                              ForeignKey("campaigns.id", name="fk_measurements_campaigns"),
                              nullable=False)
    zone_id          = Column(UUID(as_uuid=True),
                              ForeignKey("environment_zones.id",
                                         name="fk_measurements_environment_zones"))
    device_id        = Column(UUID(as_uuid=True),
                              ForeignKey("devices.id", name="fk_measurements_devices"))

    location         = Column(Geometry("POINT", srid=4326), nullable=False)
    altitude_m       = Column(Float)
    rssi_dbm         = Column(Float, nullable=False)
    snr_db           = Column(Float)
    spreading_factor = Column(SmallInteger)
    bandwidth_khz    = Column(SmallInteger)
    coding_rate      = Column(SmallInteger)
    tx_power_dbm     = Column(Float)
    frame_count      = Column(Integer)
    measured_at      = Column(DateTime(timezone=True), nullable=False)
    hdop             = Column(Float)
    data_source      = Column(String(20), nullable=False, server_default="manual")

    created_at       = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at       = Column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_measurements"),
        # CHECK constraints
        CheckConstraint("rssi_dbm >= -200 AND rssi_dbm <= 20",
                        name="ck_measurements_rssi_range"),
        CheckConstraint(
            "snr_db IS NULL OR (snr_db >= -30 AND snr_db <= 30)",
            name="ck_measurements_snr_range"),
        CheckConstraint(
            "spreading_factor IS NULL OR (spreading_factor BETWEEN 7 AND 12)",
            name="ck_measurements_sf_range"),
        CheckConstraint(
            "bandwidth_khz IS NULL OR bandwidth_khz IN (125, 250, 500)",
            name="ck_measurements_bw_allowed"),
        CheckConstraint(
            "coding_rate IS NULL OR (coding_rate BETWEEN 5 AND 8)",
            name="ck_measurements_cr_range"),
        CheckConstraint(
            "data_source IN ('manual', 'csv_import', 'api', 'webhook', "
            "'lpwanmapper', 'seed')",
            name="ck_measurements_data_source"),
        # Indexes
        Index("idx_measurements_gateway_id", "gateway_id"),
        Index("idx_measurements_device_id",  "device_id"),
        Index("idx_measurements_zone_id",    "zone_id"),
        Index("idx_measurements_location", "location", postgresql_using="gist"),
        # Composite
        Index("idx_measurements_campaign_id_measured_at",
              "campaign_id", "measured_at"),
        Index("idx_measurements_dedup",
              "device_id", "gateway_id", "frame_count", "measured_at"),
        # Partial cho soft-delete
        Index("idx_measurements_active_by_campaign",
              "campaign_id", "measured_at",
              postgresql_where="deleted_at IS NULL"),
    )


# ─────────────────────────────────────────────────────────────
# ml_models
# ─────────────────────────────────────────────────────────────
class MlModel(Base):
    __tablename__ = "ml_models"

    id                 = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    name               = Column(String(255), nullable=False)
    algorithm          = Column(String(50), nullable=False)
    version            = Column(String(50))
    rmse_db            = Column(Float)
    mae_db             = Column(Float)
    r2_score           = Column(Float)
    hyperparameters    = Column(JSONB)
    feature_importance = Column(JSONB)
    mlflow_run_id      = Column(String(255))
    trained_at         = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    created_at         = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at         = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at         = Column(DateTime(timezone=True))

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_ml_models"),
        CheckConstraint(
            "algorithm IN ('idw', 'kriging', 'xgboost', 'random_forest', "
            "'gaussian_process', 'okumura_hata', 'log_distance')",
            name="ck_ml_models_algorithm"),
        Index("idx_ml_models_algorithm", "algorithm",
              postgresql_where="deleted_at IS NULL"),
    )


# ─────────────────────────────────────────────────────────────
# ml_predictions (không còn residual_db — dùng view tính on-demand)
# ─────────────────────────────────────────────────────────────
class MlPrediction(Base):
    __tablename__ = "ml_predictions"

    id                     = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    measurement_id         = Column(UUID(as_uuid=True),
                                    ForeignKey("measurements.id", ondelete="CASCADE",
                                               name="fk_ml_predictions_measurements"),
                                    nullable=False)
    model_id               = Column(UUID(as_uuid=True),
                                    ForeignKey("ml_models.id",
                                               name="fk_ml_predictions_ml_models"),
                                    nullable=False)
    predicted_rssi_dbm     = Column(Float, nullable=False)
    prediction_uncertainty = Column(Float)
    feature_values         = Column(JSONB)
    created_at             = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_ml_predictions"),
        Index("idx_ml_predictions_measurement_id", "measurement_id"),
        Index("idx_ml_predictions_model_id",       "model_id"),
    )


# ─────────────────────────────────────────────────────────────
# prediction_grids
# ─────────────────────────────────────────────────────────────
class PredictionGrid(Base):
    __tablename__ = "prediction_grids"

    id                 = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    model_id           = Column(UUID(as_uuid=True),
                                ForeignKey("ml_models.id",
                                           name="fk_prediction_grids_ml_models"),
                                nullable=False)
    campaign_id        = Column(UUID(as_uuid=True),
                                ForeignKey("campaigns.id",
                                           name="fk_prediction_grids_campaigns"),
                                nullable=False)
    location           = Column(Geometry("POINT", srid=4326), nullable=False)
    predicted_rssi_dbm = Column(Float, nullable=False)
    uncertainty        = Column(Float)
    grid_resolution_m  = Column(Integer, nullable=False, server_default="50")
    created_at         = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_prediction_grids"),
        CheckConstraint(
            "grid_resolution_m > 0 AND grid_resolution_m <= 1000",
            name="ck_prediction_grids_resolution"),
        Index("idx_prediction_grids_model_id", "model_id"),
        Index("idx_prediction_grids_location", "location", postgresql_using="gist"),
        Index("idx_prediction_grids_campaign_rssi",
              "campaign_id", "predicted_rssi_dbm"),
    )


# ─────────────────────────────────────────────────────────────
# heatmap_caches (có TTL)
# ─────────────────────────────────────────────────────────────
class HeatmapCache(Base):
    __tablename__ = "heatmap_caches"

    id           = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    campaign_id  = Column(UUID(as_uuid=True),
                          ForeignKey("campaigns.id", ondelete="CASCADE",
                                     name="fk_heatmap_caches_campaigns"),
                          nullable=False)
    model_id     = Column(UUID(as_uuid=True),
                          ForeignKey("ml_models.id",
                                     name="fk_heatmap_caches_ml_models"),
                          nullable=False)
    zoom_level   = Column(SmallInteger, nullable=False)
    tile_data    = Column(JSONB, nullable=False)
    bbox         = Column(Geometry("POLYGON", srid=4326))
    generated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at   = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_heatmap_caches"),
        UniqueConstraint("campaign_id", "model_id", "zoom_level",
                         name="uq_heatmap_caches_campaign_model_zoom"),
        CheckConstraint("zoom_level BETWEEN 0 AND 22",
                        name="ck_heatmap_caches_zoom_range"),
        CheckConstraint("expires_at > generated_at",
                        name="ck_heatmap_caches_expires_after"),
        Index("idx_heatmap_caches_campaign_id", "campaign_id"),
        Index("idx_heatmap_caches_model_id",    "model_id"),
        Index("idx_heatmap_caches_bbox", "bbox", postgresql_using="gist"),
        Index("idx_heatmap_caches_expires_at", "expires_at"),
    )

# ─────────────────────────────────────────────────────────────
# aoi_polygons — Admin boundary (province / district) từ OSM
# ─────────────────────────────────────────────────────────────
class AoiPolygon(Base):
    __tablename__ = "aoi_polygons"
 
    id              = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    slug            = Column(String(100), nullable=False)
    name            = Column(String(255), nullable=False)
    admin_level     = Column(SmallInteger, nullable=False)
    osm_relation_id = Column(BigInteger)
    boundary        = Column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)
    properties      = Column(JSONB, nullable=False, server_default="{}")
    fetched_at      = Column(DateTime(timezone=True), nullable=False)
 
    created_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at      = Column(DateTime(timezone=True))
 
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_aoi_polygons"),
        UniqueConstraint("slug", name="uq_aoi_polygons_slug"),
        CheckConstraint("admin_level BETWEEN 2 AND 12",
                        name="ck_aoi_polygons_admin_level"),
        Index("idx_aoi_polygons_boundary", "boundary", postgresql_using="gist"),
        Index("idx_aoi_polygons_admin_level", "admin_level",
              postgresql_where="deleted_at IS NULL"),
    )

# ─────────────────────────────────────────────────────────────
# gateway_candidates — vị trí ứng viên đặt gateway (H3 hex grid)
# ─────────────────────────────────────────────────────────────
class GatewayCandidate(Base):
    __tablename__ = "gateway_candidates"
 
    id            = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    aoi_id        = Column(UUID(as_uuid=True),
                            ForeignKey("aoi_polygons.id", ondelete="CASCADE",
                                       name="fk_gateway_candidates_aoi_polygons"),
                            nullable=False)
    h3_index      = Column(String(16), nullable=False)
    h3_resolution = Column(SmallInteger, nullable=False)
    location      = Column(Geometry("POINT", srid=4326), nullable=False)
    cost          = Column(Numeric(8, 3), nullable=False, server_default="1.000")
    source        = Column(String(20), nullable=False, server_default="grid")
    properties    = Column(JSONB, nullable=False, server_default="{}")
    created_at    = Column(DateTime(timezone=True), nullable=False,
                            server_default=func.now())
 
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_gateway_candidates"),
        UniqueConstraint("aoi_id", "h3_index",
                         name="uq_gateway_candidates_aoi_h3"),
        CheckConstraint("h3_resolution BETWEEN 0 AND 15",
                        name="ck_gateway_candidates_h3_resolution"),
        CheckConstraint("source IN ('grid', 'infra')",
                        name="ck_gateway_candidates_source"),
        CheckConstraint("cost >= 0",
                        name="ck_gateway_candidates_cost"),
        Index("idx_gateway_candidates_aoi_id", "aoi_id"),
        Index("idx_gateway_candidates_location", "location",
              postgresql_using="gist"),
        Index("idx_gateway_candidates_source", "source"),
    )

# ─────────────────────────────────────────────────────────────
# optimization_runs — kết quả greedy MCLP / LSCP (audit + A/B testing)
# ─────────────────────────────────────────────────────────────
class OptimizationRun(Base):
    __tablename__ = "optimization_runs"
 
    id                   = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    aoi_id               = Column(UUID(as_uuid=True),
                                   ForeignKey("aoi_polygons.id", ondelete="CASCADE",
                                              name="fk_optimization_runs_aoi_polygons"),
                                   nullable=False)
 
    # Input
    mode                 = Column(String(10), nullable=False)
    k_max                = Column(SmallInteger)
    target_coverage      = Column(Numeric(5, 4))
    cost_aware           = Column(Boolean, nullable=False, server_default="true")
 
    # Config snapshot
    coverage_config      = Column(JSONB, nullable=False)
    coverage_config_hash = Column(String(8), nullable=False)
 
    # Result
    selection_details    = Column(JSONB, nullable=False)
    n_selected           = Column(SmallInteger, nullable=False)
    total_coverage_w     = Column(Numeric(14, 4), nullable=False)
    coverage_ratio       = Column(Numeric(5, 4), nullable=False)
    total_cost           = Column(Numeric(10, 3), nullable=False)
    n_iterations         = Column(SmallInteger, nullable=False)
    compute_ms           = Column(Integer, nullable=False)
 
    # Audit
    correlation_id       = Column(String(64))
    notes                = Column(Text)
 
    created_at           = Column(DateTime(timezone=True), nullable=False,
                                   server_default=func.now())
    updated_at           = Column(DateTime(timezone=True), nullable=False,
                                   server_default=func.now())
    deleted_at           = Column(DateTime(timezone=True))
 
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_optimization_runs"),
        CheckConstraint("mode IN ('mclp', 'lscp')",
                        name="ck_optimization_runs_mode"),
        CheckConstraint(
            "mode <> 'mclp' OR (k_max IS NOT NULL AND k_max > 0)",
            name="ck_optimization_runs_mclp_k"),
        CheckConstraint(
            "mode <> 'lscp' OR "
            "(target_coverage IS NOT NULL AND target_coverage > 0 "
            " AND target_coverage <= 1)",
            name="ck_optimization_runs_lscp_target"),
        CheckConstraint("n_selected >= 0",
                        name="ck_optimization_runs_n_selected"),
        CheckConstraint("coverage_ratio BETWEEN 0 AND 1",
                        name="ck_optimization_runs_coverage_ratio"),
        CheckConstraint("compute_ms >= 0",
                        name="ck_optimization_runs_compute_ms"),
        Index("idx_optimization_runs_aoi_created", "aoi_id", "created_at",
              postgresql_where="deleted_at IS NULL"),
        Index("idx_optimization_runs_mode", "mode",
              postgresql_where="deleted_at IS NULL"),
        Index("idx_optimization_runs_config_hash", "coverage_config_hash",
              postgresql_where="deleted_at IS NULL"),
    )

# ─────────────────────────────────────────────────────────────
# path_loss_calibrations — fitted Log-Distance model per environment_type
# ─────────────────────────────────────────────────────────────
class PathLossCalibration(Base):
    __tablename__ = "path_loss_calibrations"
 
    id                   = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    environment_type     = Column(String(50), nullable=False)
 
    # Fitted params
    n_path_loss_exponent = Column(Numeric(5, 3), nullable=False)
    intercept_db         = Column(Numeric(7, 3), nullable=False)
    sigma_db             = Column(Numeric(5, 2), nullable=False)
 
    # Goodness of fit
    r_squared            = Column(Numeric(6, 5), nullable=False)
    rmse_db              = Column(Numeric(5, 2), nullable=False)
    mae_db               = Column(Numeric(5, 2), nullable=False)
 
    # Sample meta
    n_samples_total      = Column(Integer, nullable=False)
    n_samples_fitted     = Column(Integer, nullable=False)
    n_outliers_removed   = Column(Integer, nullable=False, server_default="0")
    distance_min_m       = Column(Numeric(10, 2))
    distance_max_m       = Column(Numeric(10, 2))
 
    # Filter snapshot — recovery
    measurement_filters  = Column(JSONB, nullable=False)
 
    # Active flag
    is_active            = Column(Boolean, nullable=False, server_default="false")
 
    # Audit
    correlation_id       = Column(String(64))
    notes                = Column(Text)
 
    created_at           = Column(DateTime(timezone=True), nullable=False,
                                   server_default=func.now())
    updated_at           = Column(DateTime(timezone=True), nullable=False,
                                   server_default=func.now())
    deleted_at           = Column(DateTime(timezone=True))
 
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_path_loss_calibrations"),
        CheckConstraint(
            "environment_type IN ('urban', 'suburban', 'rural', "
            "'forest', 'coastal', 'mountain')",
            name="ck_path_loss_calibrations_env"),
        # Physics range — ITU-R P.1411 / Rappaport
        CheckConstraint(
            "n_path_loss_exponent >= 1.6 AND n_path_loss_exponent <= 6.0",
            name="ck_path_loss_calibrations_n"),
        CheckConstraint("sigma_db >= 0 AND sigma_db <= 30",
                        name="ck_path_loss_calibrations_sigma"),
        CheckConstraint("r_squared >= 0 AND r_squared <= 1",
                        name="ck_path_loss_calibrations_r2"),
        CheckConstraint("rmse_db >= 0",
                        name="ck_path_loss_calibrations_rmse"),
        CheckConstraint(
            "n_samples_fitted >= 30 "
            "AND n_samples_total >= n_samples_fitted "
            "AND n_outliers_removed >= 0",
            name="ck_path_loss_calibrations_n_samples"),
        Index("idx_path_loss_calibrations_env_active", "environment_type",
              postgresql_where="is_active = TRUE AND deleted_at IS NULL"),
        Index("idx_path_loss_calibrations_env_created",
              "environment_type", "created_at",
              postgresql_where="deleted_at IS NULL"),
        Index("uq_path_loss_calibrations_env_active", "environment_type",
              unique=True,
              postgresql_where="is_active = TRUE AND deleted_at IS NULL"),
    )