"""
tests/test_smoke.py — Smoke test 7 endpoint trọng yếu.

Gọi qua HTTP thật (http://localhost:8000) thay vì ASGI transport
để tránh bug event loop với BaseHTTPMiddleware.

Yêu cầu: API đang chạy. Trong container `api`, gọi tới chính nó.

Chạy:
    docker compose exec api pytest tests/ -v
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

BASE_URL = "http://localhost:8000"


@pytest.fixture
async def client():
    async with AsyncClient(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# ─────────────────────────────────────────────────────────────
# 1. Health & metrics
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"


@pytest.mark.asyncio
async def test_metrics(client: AsyncClient):
    res = await client.get("/metrics")
    assert res.status_code == 200
    assert res.json()["success"] is True


# ─────────────────────────────────────────────────────────────
# 2. Campaigns / Gateways list — DB connectivity
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_campaigns(client: AsyncClient):
    res = await client.get("/api/v1/campaigns/")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)


@pytest.mark.asyncio
async def test_list_gateways(client: AsyncClient):
    res = await client.get("/api/v1/gateways/")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)


# ─────────────────────────────────────────────────────────────
# 3. Coverage check
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_coverage_check_invalid_lat(client: AsyncClient):
    res = await client.get("/api/v1/coverage/check?lat=200&lng=108")
    assert res.status_code == 422
    body = res.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_LATITUDE"


@pytest.mark.asyncio
async def test_coverage_check_valid(client: AsyncClient):
    res = await client.get("/api/v1/coverage/check?lat=16.054&lng=108.202")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert "level" in body["data"]
    assert "verdict" in body["data"]


# ─────────────────────────────────────────────────────────────
# 4. Sandbox predict
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sandbox_predict_point(client: AsyncClient):
    body = {
        "txLat": 16.054, "txLng": 108.202,
        "rxLat": 16.060, "rxLng": 108.210,
        "txPowerDbm": 14, "antennaGainDbi": 8,
        "environment": "urban",
        "spreadingFactor": 9,
    }
    res = await client.post("/api/v1/sandbox/predict-point", json=body)
    assert res.status_code == 200
    data = res.json()["data"]
    assert -200 < data["predictedRssiDbm"] < 0
    assert data["pathLossDb"] > 0
    assert data["distanceM"] > 0
    assert data["level"] in ("strong", "medium", "weak", "none")


# ─────────────────────────────────────────────────────────────
# 5. Multi-tenant header
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_project_id_header(client: AsyncClient):
    res = await client.get(
        "/api/v1/gateway-health/",
        headers={"X-Project-Id": "not-a-uuid"},
    )
    assert res.status_code == 422
    body = res.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_PROJECT_ID"