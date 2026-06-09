# syntax=docker/dockerfile:1.7
# Pattern mirror services/api-service/Dockerfile: tách uv sync thành deps-only
# + project-install để layer deps stable khi sửa code. Cache mount tăng tốc
# wheel download khi lock thay đổi.

ARG PYTHON_VERSION=3.12.7

# ---- Builder stage ----
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

WORKDIR /build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Workspace skeleton — uv cần root pyproject + tất cả member pyproject để resolve.
# KHÔNG copy src ở đây — tách xuống để layer deps cache stable.
COPY pyproject.toml uv.lock /build/
COPY services/ml-service/pyproject.toml /build/services/ml-service/pyproject.toml
COPY services/ml-service/README.md /build/services/ml-service/
COPY services/api-service/pyproject.toml /build/services/api-service/pyproject.toml
COPY services/worker-service/pyproject.toml /build/services/worker-service/pyproject.toml
COPY packages/sdk-python/pyproject.toml /build/packages/sdk-python/pyproject.toml
# Vendored crc-covlib wheel — uv.lock workspace yêu cầu kể cả khi ml-service
# không runtime-dùng (api-service mới gọi crc-covlib).
COPY vendor /build/vendor

ENV UV_LINK_MODE=copy

# Deps-only install — cache mount reuse wheels giữa các build. Layer cache hit
# khi pyproject + lock không đổi → rebuild khi chỉ sửa code Python sẽ skip layer
# này hoàn toàn.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package lora-ml-predict --no-dev --frozen --no-editable --no-install-project

# Src + reference_wireless copy XUỐNG ĐÂY — sửa code chỉ invalidate layer này
# + project-install bên dưới.
COPY services/ml-service/src /build/services/ml-service/src
COPY services/ml-service/reference_wireless /build/services/ml-service/reference_wireless

# Project install — deps đã có trong .venv, uv chỉ build wheel của project.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package lora-ml-predict --no-dev --frozen --no-editable \
    && cp -r .venv /install

# ---- Runtime stage ----
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/install/lib/python3.12/site-packages"

RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
        libexpat1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --no-create-home --shell /sbin/nologin app

WORKDIR /app
COPY --from=builder /install /install

USER app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/healthz', timeout=3)"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "lora_ml_predict.app"]
