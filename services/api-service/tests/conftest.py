"""Shared pytest fixtures cho api-service test suite.

Theo unit-test-guide.md §2 Principle 2 — pull complexity vào fixtures.
Mọi default ở đây là valid + boring để test bodies chỉ đề cập field
liên quan tới behavior đang test.

Side effect: load `.env.test` ở repo root TRƯỚC khi bất cứ test nào
import code application. DB integration tests đọc DATABASE_URL từ env;
nếu thiếu thì test self-skip (xem tests/integration/test_predict_endpoint.py).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Repo root: services/api-service/tests/conftest.py → 3 levels up.
_ENV_TEST = Path(__file__).resolve().parents[3] / ".env.test"
load_dotenv(_ENV_TEST, override=False)

from lora_coverage_api.domain.coverage import Gateway, Prediction, Target
from lora_coverage_api.domain.survey import SurveyBatch, SurveyRecord

from .factories import (
    DA_NANG_LAT,
    DA_NANG_LNG,
    make_gateway,
    make_prediction,
    make_survey_batch,
    make_survey_record,
    make_target,
)


@pytest.fixture
def da_nang_coords() -> tuple[float, float]:
    return DA_NANG_LAT, DA_NANG_LNG


@pytest.fixture
def gateway_in_da_nang() -> Gateway:
    return make_gateway()


@pytest.fixture
def gateway_factory():
    """Trả callable để test tạo nhiều gateway với param khác nhau."""
    return make_gateway


@pytest.fixture
def target_in_da_nang() -> Target:
    return make_target()


@pytest.fixture
def prediction_strong() -> Prediction:
    return make_prediction()


@pytest.fixture
def survey_record_valid() -> SurveyRecord:
    return make_survey_record()


@pytest.fixture
def survey_batch_3_records() -> SurveyBatch:
    return make_survey_batch(n_records=3)
