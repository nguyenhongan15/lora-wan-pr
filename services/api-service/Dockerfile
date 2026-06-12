# syntax=docker/dockerfile:1.7
# Build context = repo root (cần workspace pyproject.toml + vendor/crc_covlib wheel).
#
# Multi-stage uv workspace install với 2 optimization:
#   1. crc-covlib build SỚM, trước uv sync — cache stable, không invalidate khi
#      sửa code Python.
#   2. uv sync TÁCH 2 BƯỚC: deps-only (no-install-project, cache mount → reuse
#      wheels) → COPY src → project install. Layer deps cache hit khi pyproject
#      + uv.lock không đổi (99% trường hợp rebuild thường chỉ sửa code).
#
# Trước fix: mỗi `up -d --build` invalidate 1.25 GB /install layer.
# Sau fix: layer deps stable; chỉ project-install layer (~MB) rebuild.

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

# Build libcrc-covlib.so từ source — TÁCH KHỎI uv sync để cache stable.
# Vendored wheel py3-none-any chỉ chứa .dll Windows; .so Linux phải build runtime.
# Inject vào site-packages ở step cuối (sau khi venv tạo xong).
#
# Repo không pin tag — clone default branch. Khi muốn reproducible build, mod
# step này thành `git clone ... && cd /tmp/crc-covlib && git checkout <SHA>`.
RUN git clone --depth 1 https://github.com/ic-crc/crc-covlib.git /tmp/crc-covlib \
    && make -C /tmp/crc-covlib rebuild \
    && mkdir -p /crc-covlib-out \
    && cp /tmp/crc-covlib/build/release/libcrc-covlib.so /crc-covlib-out/ \
    && rm -rf /tmp/crc-covlib

COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv

# Workspace skeleton — uv cần root pyproject + tất cả member pyproject để resolve.
# KHÔNG copy src ở đây — tách xuống dưới để layer deps cache stable.
COPY pyproject.toml uv.lock /build/
COPY services/api-service/pyproject.toml /build/services/api-service/pyproject.toml
COPY services/worker-service/pyproject.toml /build/services/worker-service/pyproject.toml
COPY packages/sdk-python/pyproject.toml /build/packages/sdk-python/pyproject.toml
# Vendored crc-covlib wheel (tool.uv.sources trỏ vào ../../vendor/...).
COPY vendor /build/vendor

ENV UV_LINK_MODE=copy

# Deps-only install — `--no-install-project` skip workspace member tự build,
# chỉ resolve + cài external deps. Cache mount giữ wheels giữa các build →
# rebuild deps khi lock thay đổi vẫn nhanh (reuse downloaded wheels).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package lora-coverage-api --no-dev --frozen --no-editable --no-install-project

# Src copy XUỐNG ĐÂY — sửa code Python chỉ invalidate layer này + project-install
# bên dưới. Layer deps trên cache hit.
COPY services/api-service/src /build/services/api-service/src

# Project install — deps đã có trong .venv, uv chỉ build wheel của project
# rồi cài. Layer nhẹ + nhanh. Sau đó cp venv ra /install + inject crc-covlib .so
# (gộp vào 1 RUN để giảm số layer + size).
#
# `--reinstall-package` ép uv build lại project wheel mỗi lần (bỏ qua wheel
# cache theo version-string). Cần vì rebuild thường không bump version trong
# pyproject; nếu không có flag này, uv reuse wheel cũ → COPY src/ mới bị
# "câm" → container chạy code cũ (đã debug 1 lần 2026-06-11, ~10 phút).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package lora-coverage-api --no-dev --frozen --no-editable \
        --reinstall-package lora-coverage-api \
    && cp -r .venv /install \
    && cp /crc-covlib-out/libcrc-covlib.so \
          /install/lib/python3.12/site-packages/crc_covlib/bin_64bit/libcrc-covlib.so

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
        # rasterio (cho precompute_rssi_heatmap.py qua Celery worker) cần
        # libexpat1; rasterio wheel chỉ ship GDAL còn expat phải có sẵn ở OS.
        libexpat1 \
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
