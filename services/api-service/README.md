# api-service

FastAPI 0.115+ trên Python 3.12 với 5-layer architecture.

## Layout

```
src/lora_coverage_api/
  domain/           # pure types, không I/O
    coverage.py     # Target, Prediction, Confidence, Gateway, CoverageStatus
    errors.py       # PredictionUnavailable, PredictionErrorCode
    result.py       # Result[T, E] = Ok | Err
  application/      # use cases + repository protocols
    repositories.py # CoverageQuery, GatewayDirectory protocols
    coverage_service.py
    path_loss.py    # Stage1LogDistanceModel (pure-math)
  infrastructure/   # concrete repo implementations
    db.py           # SQLAlchemy engine factory
    gateway_directory_pg.py
  edge/             # FastAPI router/middleware/serialization
    app.py          # create_app()
    deps.py         # DI wiring (chỗ DUY NHẤT biết tới infra)
    schemas.py      # Pydantic v2 request/response
    errors.py       # RFC 7807 handlers
    middleware.py   # trace_id + structured log
    routers/
      health.py     # /healthz, /readyz
      coverage.py   # POST /api/v1/coverage/predict
  config.py         # 12-Factor: env-only Settings
  main.py           # uvicorn entrypoint
```

## Chạy local

```bash
# 1. DB lên
docker compose up -d db
# 2. Migrations
uv sync
uv run alembic -c ../../migrations/alembic.ini upgrade head
psql $DATABASE_URL -f ../../migrations/seeds/seed_gateways.sql
# 3. App
uv run uvicorn lora_coverage_api.main:app --reload --port 8000
```

OpenAPI docs: http://localhost:8000/docs

## Test

```bash
# Unit (no DB)
uv run pytest tests/unit -v

# Integration (cần DATABASE_URL + migrations đã apply)
DATABASE_URL=postgresql+psycopg://lora:lora_test_pw@localhost:5432/lora_coverage \
  uv run pytest tests/integration -v
```

## Hard invariants (CI enforced)

- `application/` không import `infrastructure/` (import-linter)
- `application/` không mention các string `postgres`, `redis`, `valkey`, `s3`, `stage_4`, `GiST`, `BRIN` (CI grep)
- Mọi `Prediction` có `Confidence` (enforce ở `domain.coverage.Prediction.__post_init__`)
