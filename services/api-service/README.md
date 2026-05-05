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

Test layout mirror production (theo `core-logic/main-logic/unit-test-guide.md`):

```
tests/
  factories.py          # Value-object builders (defaults valid + boring)
  conftest.py           # Shared fixtures + load_dotenv(.env.test)
  fakes/                # In-memory implementations cho Protocol
  domain/               # Invariant tests (pure)
  application/          # Service tests (fakes, không DB)
  unit/                 # Pure-math: path_loss, Result type
  integration/          # Hit DB thật (lora_coverage_test)
```

### Setup test DB (một lần khi clone repo)

DB test dùng user/password RIÊNG (`lora_test_user` / `test_only_no_secrets`)
tách khỏi DB dev — credential này committed vào `.env.test` an toàn vì
chỉ access được DB test rỗng.

```bash
# DB container lên (xem README repo root)
docker compose up -d db

# Tạo role test + DB test (cần SUPERUSER để CREATE EXTENSION postgis/timescaledb)
docker exec lora-wan-db psql -U lora_user -d postgres -c \
  "CREATE ROLE lora_test_user LOGIN SUPERUSER PASSWORD 'test_only_no_secrets';"
docker exec lora-wan-db psql -U lora_user -d postgres -c \
  "CREATE DATABASE lora_coverage_test OWNER lora_test_user;"

# Apply migrations + seed gateways vào DB test
DATABASE_URL=postgresql+psycopg://lora_test_user:test_only_no_secrets@localhost:5432/lora_coverage_test \
  uv run alembic -c ../../migrations/alembic.ini upgrade head
docker exec -i lora-wan-db psql -U lora_test_user -d lora_coverage_test \
  < ../../migrations/seeds/seed_gateways.sql
```

### Chạy tests

```bash
# Toàn bộ — conftest tự load .env.test ở repo root
uv run pytest

# Subset
uv run pytest tests/domain tests/application   # nhanh, no I/O
uv run pytest tests/integration -v             # cần DB test sẵn sàng
```

`.env.test` được commit vào git. Credential `lora_test_user:test_only_no_secrets`
là local-only và chỉ dùng cho DB test — KHÔNG bao giờ tái sử dụng cho DB
dev hay staging/production.

## Hard invariants (CI enforced)

- `application/` không import `infrastructure/` (import-linter)
- `application/` không mention các string `postgres`, `redis`, `valkey`, `s3`, `stage_4`, `GiST`, `BRIN` (CI grep)
- Mọi `Prediction` có `Confidence` (enforce ở `domain.coverage.Prediction.__post_init__`)
