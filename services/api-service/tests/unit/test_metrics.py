"""Unit tests cho Prometheus metrics middleware + endpoint.

Test interface (4 golden signals exposed) — KHÔNG test internal collectors.
Theo unit-test-guide.md §1 Principle 1 — test the interface, not the implementation.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lora_coverage_api.edge.metrics import metrics_endpoint, metrics_middleware


def _app_with_metrics() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(metrics_middleware)
    app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)

    @app.get("/ping")
    def _ping() -> dict[str, str]:
        return {"ok": "yes"}

    return app


def test_metrics_endpoint_returns_prometheus_text() -> None:
    client = TestClient(_app_with_metrics())
    # Ping trước để có ít nhất 1 sample.
    client.get("/ping")

    r = client.get("/metrics")
    assert r.status_code == 200
    # Prometheus exposition format — text/plain với version.
    assert "text/plain" in r.headers["content-type"]
    body = r.text
    # 4 golden signals đều phải có:
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    assert "http_requests_in_flight" in body


def test_metrics_endpoint_itself_not_counted() -> None:
    client = TestClient(_app_with_metrics())
    # Gọi /metrics nhiều lần — không được tự đếm chính nó.
    for _ in range(3):
        client.get("/metrics")
    body = client.get("/metrics").text
    assert 'path="/metrics"' not in body


def test_metrics_uses_route_pattern_not_raw_path() -> None:
    """Path label PHẢI là route pattern (/items/{id}) không phải raw (/items/42).

    Lý do: cardinality. UUID/id thật làm Prometheus blow up.
    """
    app = FastAPI()
    app.middleware("http")(metrics_middleware)
    app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)

    @app.get("/items/{item_id}")
    def _get_item(item_id: int) -> dict[str, int]:
        return {"id": item_id}

    client = TestClient(app)
    client.get("/items/42")
    client.get("/items/99")

    body = client.get("/metrics").text
    assert 'path="/items/{item_id}"' in body
    assert 'path="/items/42"' not in body
    assert 'path="/items/99"' not in body
