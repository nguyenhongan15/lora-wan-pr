# api-service

FastAPI 0.115+ trên Python 3.12 với kiến trúc 5 tầng.

## Layout

```
src/lora_coverage_api/
  domain/           # type thuần, không I/O
    coverage.py     # Target, Prediction, Confidence, Gateway, CoverageStatus
    errors.py       # PredictionUnavailable, PredictionErrorCode
    result.py       # Result[T, E] = Ok | Err
  application/      # use case + repository protocol
    repositories.py # Protocol CoverageQuery, GatewayDirectory
    coverage_service.py
    path_loss.py    # link-budget helpers + PathLossModel Protocol
    itu/            # Stage1ItuModel + Stage1PhysicsBackend Protocol (ITU-R P.1812 + P.2108)
  infrastructure/   # cài đặt repo cụ thể
    db.py           # SQLAlchemy engine factory
    gateway_directory_pg.py
    itu/            # CrcCovlibBackend (crc-covlib MIT, C++ qua DEM GeoTIFF)
  edge/             # FastAPI router/middleware/serialization
    app.py          # create_app()
    deps.py         # DI wiring (chỗ DUY NHẤT biết tới infra)
    schemas.py      # Pydantic v2 request/response
    errors.py       # Handler RFC 7807
    middleware.py   # trace_id + structured log
    routers/
      health.py     # /healthz, /readyz
      coverage.py   # POST /api/v1/coverage/predict
  config.py         # 12-Factor: Settings chỉ từ env
  main.py           # entrypoint uvicorn
```

## Chạy local

```bash
# 1. DB lên
docker compose up -d db
# 2. Migration
uv sync
uv run alembic -c ../../migrations/alembic.ini upgrade head
psql $DATABASE_URL -f ../../migrations/seeds/seed_gateways.sql
# 3. App
uv run uvicorn lora_coverage_api.main:app --reload --port 8000
```

OpenAPI docs: http://localhost:8000/docs

## Test

Layout test phản chiếu production (theo `core-logic/main-logic/unit-test-guide.md`):

```
tests/
  factories.py          # Builder cho value-object (mặc định hợp lệ + tẻ nhạt)
  conftest.py           # Fixture dùng chung + load_dotenv(.env.test)
  fakes/                # Cài đặt in-memory cho Protocol
  domain/               # Test bất biến (thuần)
  application/          # Test service (dùng fake, không DB)
  unit/                 # Toán thuần: path_loss, kiểu Result
  integration/          # Đụng DB thật (lora_coverage_test)
```

### Setup DB test (một lần khi clone repo)

DB test dùng user/password RIÊNG (`lora_test_user` / `test_only_no_secrets`)
tách khỏi DB dev — credential này commit vào `.env.test` an toàn vì
chỉ access được DB test rỗng.

```bash
# DB container lên (xem README ở repo root)
docker compose up -d db

# Tạo role test + DB test (cần SUPERUSER để CREATE EXTENSION postgis/timescaledb)
docker exec lora-wan-db psql -U lora_user -d postgres -c \
  "CREATE ROLE lora_test_user LOGIN SUPERUSER PASSWORD 'test_only_no_secrets';"
docker exec lora-wan-db psql -U lora_user -d postgres -c \
  "CREATE DATABASE lora_coverage_test OWNER lora_test_user;"

# Áp dụng migration + seed gateway vào DB test
DATABASE_URL=postgresql+psycopg://lora_test_user:test_only_no_secrets@localhost:5432/lora_coverage_test \
  uv run alembic -c ../../migrations/alembic.ini upgrade head
docker exec -i lora-wan-db psql -U lora_test_user -d lora_coverage_test \
  < ../../migrations/seeds/seed_gateways.sql
```

### Chạy test

```bash
# Toàn bộ — conftest tự load .env.test ở repo root
uv run pytest

# Subset
uv run pytest tests/domain tests/application   # nhanh, không I/O
uv run pytest tests/integration -v             # cần DB test sẵn sàng
```

`.env.test` được commit vào git. Credential `lora_test_user:test_only_no_secrets`
chỉ dùng local và chỉ dành cho DB test — KHÔNG bao giờ tái sử dụng cho DB
dev hay staging/production.

## Bootstrap admin (plan-auth-v1 §3.5)

`/api/v1/admin/*` yêu cầu `is_admin=true`. Không có endpoint tự promote —
admin đầu tiên phải set thủ công trong DB sau khi register thường:

```bash
# 1. Register user qua API như mọi user bình thường:
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H 'content-type: application/json' \
  -d '{"email":"admin@example.com","password":"<strong-pw>"}'

# 2. Promote bằng SQL (cần DB role có quyền UPDATE lên auth.users):
docker exec lora-wan-db psql -U lora_user -d lora_coverage \
  -c "UPDATE auth.users SET is_admin = true WHERE email = 'admin@example.com';"
```

Tự bảo vệ: admin KHÔNG thể tự sửa `is_admin`/`disabled` của chính
mình qua API (`AdminSelfModificationError` 400). Demote/disable admin cuối
cùng → thao tác SQL trực tiếp.

## Bất biến cứng (CI enforce)

- `application/` không import `infrastructure/` (import-linter)
- `application/` không nhắc các string `postgres`, `redis`, `valkey`, `s3`, `stage_4`, `GiST`, `BRIN` (CI grep)
- Mọi `Prediction` đều có `Confidence` (enforce ở `domain.coverage.Prediction.__post_init__`)
