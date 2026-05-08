"""Integration tests cho POST /api/v1/coverage/predict.

Yêu cầu DB chạy được + đã apply migrations. Test tự seed 1 gateway gần
Đà Nẵng (code `test-pred-danang`) trong fixture nên không phụ thuộc data
production sẵn có; cleanup teardown để DB sạch sau khi chạy.
Dùng FastAPI TestClient.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from lora_coverage_api.edge.app import create_app
from lora_coverage_api.infrastructure.db import make_engine

_TEST_GATEWAY_CODE = "test-pred-danang"


@pytest.fixture(scope="module")
def client() -> TestClient:
    if "DATABASE_URL" not in os.environ:
        pytest.skip("DATABASE_URL chưa set; skip integration test.")
    return TestClient(create_app())


@pytest.fixture(scope="module")
def _seed_danang_gateway() -> None:
    """Seed 1 gateway cố định gần Đà Nẵng cho test_predict_near_danang_gateway.

    Idempotent (ON CONFLICT DO NOTHING) — nếu code đã tồn tại từ run trước thì
    skip insert. Cleanup ở teardown để không leak state qua test khác.
    """
    if "DATABASE_URL" not in os.environ:
        pytest.skip("DATABASE_URL chưa set; skip integration test.")
    engine = make_engine(os.environ["DATABASE_URL"])
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO geo.gateways (
                    code, name, location, frequency_mhz, is_public
                )
                VALUES (
                    :code, :name,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                    923.0, true
                )
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": _TEST_GATEWAY_CODE, "name": _TEST_GATEWAY_CODE,
             "lat": 16.115, "lon": 108.278},
        )
    yield
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM geo.gateways WHERE code = :code"),
            {"code": _TEST_GATEWAY_CODE},
        )


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_predict_near_danang_gateway(client: TestClient, _seed_danang_gateway: None) -> None:
    # Test chỉ assert có gateway nào đó in-range, không bind code cụ thể.
    r = client.post(
        "/api/v1/coverage/predict",
        json={
            "latitude": 16.115,
            "longitude": 108.278,
            "spreading_factor": 7,
            "frequency_mhz": 923.0,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["coverage_status"] in ("strong", "marginal")
    assert body["confidence"]["method"] == "empirical"
    assert body["model_version"].startswith("stage1-")


def test_predict_validation_error(client: TestClient) -> None:
    r = client.post(
        "/api/v1/coverage/predict",
        json={"latitude": 999, "longitude": 0, "spreading_factor": 7},
    )
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR"


def test_predict_no_gateway_in_pacific(client: TestClient) -> None:
    # Giữa Thái Bình Dương — chắc chắn không seed gateway nào.
    r = client.post(
        "/api/v1/coverage/predict",
        json={
            "latitude": 0.0,
            "longitude": -150.0,
            "spreading_factor": 7,
            "frequency_mhz": 868.0,
        },
    )
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "NO_GATEWAY_NEARBY"
