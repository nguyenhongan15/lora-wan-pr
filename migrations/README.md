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

Trong docker-compose, service `migrate` chạy `alembic upgrade head` một lần khi container `db` healthy → api-service depend on `migrate` success.

## Quy tắc

- **KHÔNG** dùng SQLAlchemy ORM autogenerate — viết DDL bằng tay (raw SQL trong `op.execute(...)`).
- Mỗi revision **PHẢI** đảo ngược được (có downgrade tương ứng), trừ khi migration dữ liệu không thể revert (phải comment giải thích).
- Tách concern: 1 revision = 1 mục đích (init schema vs tạo bảng vs hypertable vs index).
- Đặt tên: `NNNN_short_snake_case.py`.

## Layout

| Revision | Mục đích |
|---|---|
| 0001 | Init schemas (`geo`, `ts`, `auth`, `ml`) + extensions (PostGIS, TimescaleDB) |
| 0002 | `geo.gateways` table (codes, location, antenna, frequency) |
| 0003 | `ts.survey_quarantine` + `ts.survey_training` hypertable |
| 0004 | Address canonical fields trên `geo.gateways` |
| 0005 | Rename provider `postgres` → `cache` |
| 0006 | `auth.users` + `auth.linked_sources` |
| 0007 | Provenance columns (uploader_id, source_type, weight) trên survey rows |
| 0008 | Relax RSSI upper bound check constraint |
| 0009 | linked_sources credential fingerprint |
| 0010 | Gateway bidirectional fields (rx_antenna_gain_dbi, etc.) |
| 0011 | ML schema + model registry table |
| 0012 | Login lockout (rate-limit per-user) |
| 0013 | Refresh tokens table (auth v2) |
| 0014 | ChirpStack webhook tokens |
| 0015 | `geo.devices` table |
| 0016 | Password reset tokens |
| 0017 | Contribution trust columns |
| 0018 | Admin review columns (pending contribution queue) |
| 0019 | Email verification tokens |
| 0020 | Gateway per-gw noise floor (`ul_noise_floor_dbm`, `dl_thermal_dbm`) |

**Latest head:** `0020_gateway_noise_floor`.

## Seeds

| File | Mục đích |
|---|---|
| `seeds/seed_gateways.sql` | 11 gateway DNIIT Đà Nẵng + 2 Hải Phòng pilot. Idempotent (ON CONFLICT DO NOTHING). |
| `seeds/dev_pending_contributions.sql` | Test data cho admin review queue (dev only). |
