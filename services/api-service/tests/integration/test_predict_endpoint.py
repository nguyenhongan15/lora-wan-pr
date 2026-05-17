"""Integration tests cho POST /api/v1/coverage/predict.

Yêu cầu DB chạy được + đã apply migrations. Test tự seed 1 gateway gần
Đà Nẵng (code `test-pred-danang`) trong fixture nên không phụ thuộc data
production sẵn có; cleanup teardown để DB sạch sau khi chạy.
Dùng FastAPI TestClient.

Backend physics: test override `_itu_backend` thành FakeBackend deterministic
(free-space + excess) để chạy được trên CI Linux runner — môi trường này không
có `libcrc-covlib.so` (build trong Dockerfile) và không có DEM tiles thật.
Scope test này là routing/DB/bidirectional/response shape, không phải physics
— physics đã có unit test riêng trong tests/unit/test_path_loss.py.
"""

from __future__ import annotations

import math
import os
from collections.abc import Generator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from lora_coverage_api.application.itu.backend import LinkGeometry
from lora_coverage_api.edge import deps
from lora_coverage_api.edge.app import create_app
from lora_coverage_api.infrastructure.db import make_engine

_TEST_GATEWAY_CODE = "test-pred-danang"


@dataclass(frozen=True, slots=True)
class _FakeBackend:
    """PL = free-space + suburban excess (n=3). Mirror tests/unit/test_path_loss.py."""

    model_version: str = "fake-physics-v0"
    n: float = 3.0

    def basic_transmission_loss_db(self, link: LinkGeometry) -> float:
        r = 6371.0088
        p1, p2 = math.radians(link.tx.latitude), math.radians(link.rx.latitude)
        dp = math.radians(link.rx.latitude - link.tx.latitude)
        dl = math.radians(link.rx.longitude - link.tx.longitude)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        d_km = max(2 * r * math.asin(math.sqrt(a)), 0.001)
        free_space = 32.45 + 20 * math.log10(d_km) + 20 * math.log10(link.freq_mhz)
        excess = 10 * (self.n - 2) * math.log10(d_km / 0.1) if d_km > 0.1 else 0.0
        return free_space + excess


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    if "DATABASE_URL" not in os.environ:
        pytest.skip("DATABASE_URL chưa set; skip integration test.")
    # Swap real CrcCovlibBackend bằng FakeBackend — coverage_query() lookup
    # `_itu_backend` qua module namespace tại call time, nên reassignment có hiệu lực.
    original = deps._itu_backend
    deps._itu_backend = lambda: _FakeBackend()  # type: ignore[assignment]
    try:
        yield TestClient(create_app())
    finally:
        deps._itu_backend = original


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
            {"code": _TEST_GATEWAY_CODE, "name": _TEST_GATEWAY_CODE, "lat": 16.115, "lon": 108.278},
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
    assert body["confidence"]["method"] == "physics"
    assert body["model_version"].startswith("stage1-")
    # Bidirectional fields
    assert body["bottleneck"] in ("uplink", "downlink", "both_ok")
    for direction in ("uplink", "downlink"):
        link = body[direction]
        assert link["status"] in ("strong", "marginal", "weak", "no_coverage")
        assert isinstance(link["rssi_dbm"], (int, float))
        assert isinstance(link["margin_db"], (int, float))
    # Top-level rssi/snr = downlink (backward compat semantic)
    assert body["rssi_dbm"] == body["downlink"]["rssi_dbm"]
    assert body["snr_db"] == body["downlink"]["snr_db"]


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
            "frequency_mhz": 923.0,
        },
    )
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "NO_GATEWAY_NEARBY"


def test_predict_rejects_tx_power_above_as923_cap(client: TestClient) -> None:
    """tx_power_dbm > 14 → 422 ở schema (Field le=14), không vào domain."""
    r = client.post(
        "/api/v1/coverage/predict",
        json={
            "latitude": 16.115,
            "longitude": 108.278,
            "spreading_factor": 7,
            "frequency_mhz": 923.0,
            "tx_power_dbm": 17.0,
        },
    )
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR"


def test_predict_accepts_device_overrides_within_bounds(
    client: TestClient, _seed_danang_gateway: None
) -> None:
    """Override 4 device-side fields trong giới hạn → 200 + response shape full."""
    r = client.post(
        "/api/v1/coverage/predict",
        json={
            "latitude": 16.115,
            "longitude": 108.278,
            "spreading_factor": 7,
            "frequency_mhz": 923.0,
            "tx_power_dbm": 10.0,
            "tx_antenna_gain_dbi": 3.0,
            "rx_antenna_gain_dbi": 1.0,
            "rx_sensitivity_dbm": -125.0,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "uplink" in body and "downlink" in body
    assert body["bottleneck"] in ("uplink", "downlink", "both_ok")
