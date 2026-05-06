"""Integration tests cho POST /api/v1/coverage/predict.

Yêu cầu DB chạy được + đã apply migrations + đã seed gateway.
Dùng FastAPI TestClient.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from lora_coverage_api.edge.app import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    if "DATABASE_URL" not in os.environ:
        pytest.skip("DATABASE_URL chưa set; skip integration test.")
    return TestClient(create_app())


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_predict_near_danang_gateway(client: TestClient) -> None:
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
