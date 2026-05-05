# migrations

Alembic migrations cho PostgreSQL 17 + PostGIS 3.5 + TimescaleDB 2.17.

## Chạy

```bash
# 1. Đảm bảo DB lên (dev: docker compose up -d db)
# 2. Đặt DATABASE_URL hoặc dùng .env
export DATABASE_URL=postgresql+psycopg://lora:lora_test_pw@localhost:5432/lora_coverage

# 3. Apply migrations
uv run alembic -c migrations/alembic.ini upgrade head

# 4. Seed (optional, dev/demo only)
psql $DATABASE_URL -f migrations/seeds/seed_gateways.sql
```

## Quy tắc

- **KHÔNG** dùng SQLAlchemy ORM autogenerate — viết DDL bằng tay (raw SQL trong `op.execute(...)`).
- Mỗi revision **PHẢI** reversible (có downgrade tương ứng), trừ khi data-migration không thể revert (phải comment giải thích).
- Tách concern: 1 revision = 1 mục đích (init schemas vs tạo bảng vs hypertable vs index).
- Đặt tên: `NNNN_short_snake_case.py`.

## Layout

| File | Mục đích |
|------|----------|
| `alembic.ini` | Cấu hình Alembic (đọc DATABASE_URL từ env) |
| `env.py` | Migration runner (online/offline) |
| `script.py.mako` | Template revision |
| `versions/0001_init_schemas_and_extensions.py` | Schemas + extensions (postgis, timescaledb, unaccent, pg_trgm, pgcrypto) |
| `versions/0002_geo_gateways.py` | Bảng `geo.gateways` + GiST index |
| `seeds/` | Seed data (dev/demo only) |

## Sắp tới (chưa làm ở v0)

- `0003_ts_survey_quarantine.py` — hypertable quarantine
- `0004_ts_survey_training.py` — hypertable training (riêng biệt)
- `0005_address_canonical.py` — bảng địa chỉ + generated column unaccent
- `0006_audit_compliance_log.py` — plain table
