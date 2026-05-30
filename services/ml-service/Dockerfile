# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.12.7

# ---- Builder stage ----
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

WORKDIR /build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Workspace skeleton
COPY pyproject.toml uv.lock /build/
COPY services/ml-service/pyproject.toml /build/services/ml-service/pyproject.toml
COPY services/ml-service/README.md /build/services/ml-service/
COPY services/ml-service/src /build/services/ml-service/src
COPY services/ml-service/reference_wireless /build/services/ml-service/reference_wireless
# Add other workspace members if needed for dependency resolution
COPY services/api-service/pyproject.toml /build/services/api-service/pyproject.toml
COPY services/worker-service/pyproject.toml /build/services/worker-service/pyproject.toml
COPY packages/sdk-python/pyproject.toml /build/packages/sdk-python/pyproject.toml
# Vendored crc-covlib wheel — uv.lock workspace yêu cầu kể cả khi ml-service
# không runtime-dùng (api-service mới gọi crc-covlib).
COPY vendor /build/vendor

ENV UV_LINK_MODE=copy
RUN uv sync --package lora-ml-predict --no-dev --frozen --no-editable \
    && cp -r .venv /install

# ---- Runtime stage ----
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/install/lib/python3.12/site-packages"

RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
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
