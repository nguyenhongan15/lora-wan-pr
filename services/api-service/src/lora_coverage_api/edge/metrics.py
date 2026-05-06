"""Prometheus metrics — 4 golden signals (latency / traffic / errors / saturation).

Theo rule-backup-recovery-monitoring-logging.md §3.1.4 và rule-design-observability.md.
Endpoint /metrics exposed cho Prometheus scrape.

Label cardinality kept low:
  - `method`: chỉ vài giá trị (GET/POST/PATCH/...)
  - `path`: lấy *route pattern* sau khi router match (vd /api/v1/gateways/{id}),
    không phải raw path → tránh blow-up với UUID.
  - `status`: HTTP status code (3 chữ số).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.responses import Response as StarletteResponse

# Registry riêng cho app — giữ test isolation, không lẫn process-wide default.
REGISTRY = CollectorRegistry()

# ── Traffic + Errors ───────────────────────────────────────────────────────
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests processed",
    labelnames=("method", "path", "status"),
    registry=REGISTRY,
)

# ── Latency ────────────────────────────────────────────────────────────────
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    labelnames=("method", "path", "status"),
    # Buckets phù hợp với SLO P95 < 3s cho /lookup (system-design.md SLA).
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

# ── Saturation ─────────────────────────────────────────────────────────────
HTTP_REQUESTS_IN_FLIGHT = Gauge(
    "http_requests_in_flight",
    "Number of HTTP requests currently being processed",
    registry=REGISTRY,
)

# ── F2 lookup SLO ──────────────────────────────────────────────────────────
# Histogram chuyên biệt cho /coverage/lookup — labels giúp tách theo provider
# (postgres-cache / nominatim / vietmap / goong) và outcome (ok/error). Cho
# phép alert P95 theo từng provider thay vì avg toàn cục.
#
# Tách khỏi http_request_duration_seconds vì:
#   * label set khác (provider, outcome) — nếu nhồi vào generic histogram
#     sẽ blow-up cardinality do path × method × status × provider × outcome.
#   * SLO budget 3s là số đặc thù cho lookup — bucket riêng tối ưu cho range
#     0.1..5s thay vì 0.01..10s của generic.
LOOKUP_LATENCY_SECONDS = Histogram(
    "lookup_latency_seconds",
    "F2 /coverage/lookup end-to-end latency (geocode + predict + render).",
    labelnames=("provider", "outcome"),
    # Bucket dày quanh SLO 3s; cap 6s để vẫn đo được tail dài (P99).
    buckets=(0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0),
    registry=REGISTRY,
)

LOOKUP_SLO_VIOLATIONS_TOTAL = Counter(
    "lookup_slo_violations_total",
    "Số request /coverage/lookup vượt SLO budget (lookup_slo_seconds).",
    labelnames=("provider", "outcome"),
    registry=REGISTRY,
)


def _route_pattern(request: Request) -> str:
    """Trả route pattern (vd /api/v1/gateways/{id}) sau khi router match.

    Fallback về raw path nếu chưa match (404, OPTIONS không có route).
    Lý do dùng pattern: tránh label cardinality nổ với UUID/id thật.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else request.url.path


async def metrics_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Ghi metrics cho mọi HTTP request — PHẢI chạy sau routing để có path pattern."""
    # /metrics tự nó không nên được tính vào metrics (tránh self-loop noise).
    if request.url.path == "/metrics":
        return await call_next(request)

    HTTP_REQUESTS_IN_FLIGHT.inc()
    start = time.perf_counter()
    try:
        response = await call_next(request)
        status = str(response.status_code)
    except Exception:
        # Unhandled exception → error_handler trả 500, nhưng nếu rớt qua đây
        # vẫn phải ghi metric để không thấy "missing" trên dashboard.
        elapsed = time.perf_counter() - start
        path = _route_pattern(request)
        HTTP_REQUESTS_TOTAL.labels(request.method, path, "500").inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            request.method, path, "500"
        ).observe(elapsed)
        HTTP_REQUESTS_IN_FLIGHT.dec()
        raise

    elapsed = time.perf_counter() - start
    path = _route_pattern(request)
    HTTP_REQUESTS_TOTAL.labels(request.method, path, status).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(request.method, path, status).observe(elapsed)
    HTTP_REQUESTS_IN_FLIGHT.dec()
    return response


def metrics_endpoint() -> StarletteResponse:
    """`GET /metrics` — Prometheus scrape target.

    Trả text/plain theo Prometheus exposition format.
    KHÔNG cần auth ở app layer; production phải block từ ingress
    (chỉ allow private network) — xem rule-design-security.md.
    """
    payload = generate_latest(REGISTRY)
    return StarletteResponse(content=payload, media_type=CONTENT_TYPE_LATEST)
