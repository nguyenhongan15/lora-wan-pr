# ── Stage 1: build deps ─────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgdal-dev libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev libpq5 curl fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app

# Non-root user — bảo mật, không chạy app với root
RUN useradd -m -u 1000 appuser

COPY --chown=appuser:appuser . .

# Thư mục cần ghi
RUN mkdir -p static ml_models && chown -R appuser:appuser static ml_models

USER appuser

EXPOSE 8000

# HEALTHCHECK dùng /health endpoint public
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Factor 9 (Disposability): lifespan handler ở main.py lo graceful shutdown
# uvicorn tự handle SIGTERM → gọi lifespan cleanup
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info", "--no-access-log"]
