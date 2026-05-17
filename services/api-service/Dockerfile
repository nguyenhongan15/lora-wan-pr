# syntax=docker/dockerfile:1.7
# Build context = repo root (cần workspace pyproject.toml + vendor/crc_covlib wheel).
#
# Multi-stage uv workspace install — mirror services/ml-service-predict/Dockerfile.

ARG PYTHON_VERSION=3.12.7

# ---- Builder stage ----
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        cmake \
        libtiff-dev \
        libgeotiff-dev \
        libgeographiclib-dev \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv

# Workspace skeleton — uv cần root pyproject + tất cả member pyproject để resolve.
COPY pyproject.toml uv.lock /build/
COPY services/api-service/pyproject.toml /build/services/api-service/pyproject.toml
COPY services/api-service/src /build/services/api-service/src
COPY services/ml-service-predict/pyproject.toml /build/services/ml-service-predict/pyproject.toml
COPY services/ml-service-hmap/pyproject.toml /build/services/ml-service-hmap/pyproject.toml
COPY services/worker-service/pyproject.toml /build/services/worker-service/pyproject.toml
COPY packages/sdk-python/pyproject.toml /build/packages/sdk-python/pyproject.toml
# Vendored crc-covlib wheel (tool.uv.sources trỏ vào ../../vendor/...).
# Wheel chỉ chứa crc-covlib.dll (Windows); .so Linux build ở step kế tiếp.
COPY vendor /build/vendor

ENV UV_LINK_MODE=copy
RUN uv sync --package lora-coverage-api --no-dev --frozen --no-editable \
    && cp -r .venv /install

# Build libcrc-covlib.so từ source (vendored wheel py3-none-any chỉ chứa .dll
# Windows). Inject vào site-packages/crc_covlib/bin_64bit/ để ctypes loader
# (simulation.py:84-87) tìm thấy trên Linux.
# Repo không có tag v4.6.2 — pin SHA sau khi smoke test pass nếu muốn
# reproducible build hoàn toàn; main hiện tại ABI-compatible (cùng struct
# layouts với PyPI 4.6.2 tại 2026-05).
RUN git clone --depth 1 https://github.com/ic-crc/crc-covlib.git /tmp/crc-covlib \
    && make -C /tmp/crc-covlib rebuild \
    && cp /tmp/crc-covlib/build/release/libcrc-covlib.so \
          /install/lib/python3.12/site-packages/crc_covlib/bin_64bit/libcrc-covlib.so \
    && rm -rf /tmp/crc-covlib

# ---- Runtime stage ----
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/install/lib/python3.12/site-packages"

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libtiff6 \
        libgeotiff5 \
        libgeographiclib23 \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --no-create-home --shell /sbin/nologin app

WORKDIR /app
COPY --from=builder /install /install

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]

STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "uvicorn", "lora_coverage_api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--no-access-log"]
