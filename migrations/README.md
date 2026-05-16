# migrations

Alembic migration cho PostgreSQL 17 + PostGIS 3.5 + TimescaleDB 2.17.

## Chạy

```bash
# 1. Đảm bảo DB đang chạy (dev: docker compose up -d db)
# 2. Đặt DATABASE_URL hoặc dùng .env
export DATABASE_URL=postgresql+psycopg://lora:lora_test_pw@localhost:5432/lora_coverage

# 3. Áp dụng migration
uv run alembic -c migrations/alembic.ini upgrade head

# 4. Seed (tùy chọn, chỉ dev/demo)
psql $DATABASE_URL -f migrations/seeds/seed_gateways.sql
```

## Quy tắc

- **KHÔNG** dùng SQLAlchemy ORM autogenerate — viết DDL bằng tay (raw SQL trong `op.execute(...)`).
- Mỗi revision **PHẢI** đảo ngược được (có downgrade tương ứng), trừ khi migration dữ liệu không thể revert (phải comment giải thích).
- Tách concern: 1 revision = 1 mục đích (init schema vs tạo bảng vs hypertable vs index).
- Đặt tên: `NNNN_short_snake_case.py`.

## Layout

| File | Mục đích |
|------|----------|



