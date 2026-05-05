"""Dependency injection wiring.

Edge là chỗ DUY NHẤT biết tới infrastructure. Application chỉ thấy protocols.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine

from ..application.coverage_service import CoverageQueryService
from ..application.path_loss import Stage1LogDistanceModel
from ..application.repositories import CoverageQuery, GatewayDirectory, SurveyIngest
from ..application.survey_service import SurveyIngestService
from ..config import Settings, get_settings
from ..infrastructure.db import make_engine
from ..infrastructure.gateway_directory_pg import PgGatewayDirectory
from ..infrastructure.survey_repository_pg import PgSurveyRepository


@lru_cache(maxsize=1)
def _settings() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def _engine() -> Engine:
    return make_engine(_settings().database_url)


def gateway_directory() -> GatewayDirectory:
    return PgGatewayDirectory(_engine())


def survey_repository() -> SurveyIngest:
    return PgSurveyRepository(_engine())


def coverage_query() -> CoverageQuery:
    settings = _settings()
    return CoverageQueryService(
        directory=gateway_directory(),
        model=Stage1LogDistanceModel(model_version=settings.ml_model_version),
    )


def survey_service() -> SurveyIngestService:
    return SurveyIngestService(repository=survey_repository())
