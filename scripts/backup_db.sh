#!/usr/bin/env bash
# Pre-deploy DB snapshot — chạy TRƯỚC `docker compose up` khi deploy bản mới.
# Mục đích: rollback an toàn khi migration mới phá data (DROP COLUMN, type
# change). Image rollback nhanh nhưng schema đi 1 chiều — cần dump để khôi
# phục bảng nếu downgrade alembic không undo được data.
#
# Usage:
#   ./scripts/backup_db.sh                 # → backups/lora_coverage_<sha>_<ts>.sql.gz
#   ./scripts/backup_db.sh /mnt/backup     # → custom dir
#
# Restore (khi rollback fail tới mức cần data cũ):
#   gunzip -c backups/<file>.sql.gz | docker exec -i lora-wan-db \
#       psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

set -euo pipefail

BACKUP_DIR="${1:-./backups}"
mkdir -p "$BACKUP_DIR"

# Load .env nếu có (POSTGRES_USER, POSTGRES_DB).
if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

: "${POSTGRES_USER:?POSTGRES_USER chưa set}"
: "${POSTGRES_DB:?POSTGRES_DB chưa set}"

SHA="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$BACKUP_DIR/lora_coverage_${SHA}_${TS}.sql.gz"

echo "→ Dump $POSTGRES_DB từ container lora-wan-db ..."
docker exec lora-wan-db pg_dump \
    --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB" \
    --format=plain \
    --no-owner \
    --no-privileges \
    | gzip -9 > "$OUT"

SIZE=$(du -h "$OUT" | cut -f1)
echo "✓ $OUT ($SIZE)"

# Retention: giữ 10 dump gần nhất, xoá phần thừa. Tránh ngập disk khi
# deploy thường xuyên.
ls -1t "$BACKUP_DIR"/lora_coverage_*.sql.gz 2>/dev/null \
    | tail -n +11 \
    | xargs -r rm -v
