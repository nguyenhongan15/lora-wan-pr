# syntax=docker/dockerfile:1.7
# Build context = repo root (cần workspace pyproject.toml + lora-coverage-api source).
#
# Multi-stage: builder dùng uv để resolve workspace, runtime slim chỉ giữ
# Python site-packages + native deps (libpq, GDAL cho rasterio, libgomp cho LightGBM).

ARG PYTHON_VERSION=3.12.7

# ---- Builder stage ----
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        ca-certificates \
        cmake \
        libtiff-dev \
        libgeotiff-dev \
        libgeographiclib-dev \
        git \
    && rm -rf /var/lib/apt/lists/*

# uv (single binary, resolve workspace).
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv

# Copy workspace skeleton + service code. Workspace pyproject.toml ở root —
# uv cần thấy nó + cả 2 service pyproject.toml để resolve workspace dep.
COPY pyproject.toml uv.lock /build/
COPY services/api-service/pyproject.toml /build/services/api-service/pyproject.toml
COPY services/api-service/src /build/services/api-service/src
COPY services/ml-service/pyproject.toml /build/services/ml-service/pyproject.toml
COPY services/ml-service/src /build/services/ml-service/src
COPY services/ml-service/scripts /build/services/ml-service/scripts
# Workspace marker: cần các member khác tồn tại (uv sẽ load tất cả).
COPY services/worker-service/pyproject.toml /build/services/worker-service/pyproject.toml
COPY packages/sdk-python/pyproject.toml /build/packages/sdk-python/pyproject.toml
# Vendored crc-covlib wheel (tool.uv.sources trỏ vào ../../vendor/...).
COPY vendor /build/vendor

# uv sync ml-service + workspace dep lora-coverage-api. --no-editable để
# workspace member install ra site-packages (không phải .pth → source dir), tránh
# editable .pth còn point tới /build (đã discard ở runtime stage).
ENV UV_LINK_MODE=copy
RUN uv sync --package lora-ml-predict --no-dev --frozen --no-editable \
    && cp -r .venv /install

# Build libcrc-covlib.so từ source (vendored wheel py3-none-any chỉ chứa .dll
# Windows). Inject vào site-packages/crc_covlib/bin_64bit/ để ctypes loader
# tìm thấy trên Linux. Xem comment chi tiết ở services/api-service/Dockerfile.
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
        libgomp1 \
        libexpat1 \
        libtiff6 \
        libgeotiff5 \
        libgeographiclib23 \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --no-create-home --shell /sbin/nologin app

WORKDIR /app
COPY --from=builder /install /install
COPY services/ml-service/scripts /app/scripts

USER app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/healthz', timeout=3)"]

STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/bin/tini", "--"]
# python -m uvicorn (không gọi /install/bin/uvicorn) vì shebang trong script đó
# trỏ tới builder venv `/build/.venv/bin/python` không tồn tại ở runtime stage.
CMD ["python", "-m", "uvicorn", "lora_ml_predict.serving.server:app", \
     "--host", "0.0.0.0", \
     "--port", "8001", \
     "--workers", "1", \
     "--no-access-log"]
