#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# LoRa Coverage Platform — setup 1 lệnh cho máy mới (fresh clone).
#
#   ./setup.sh          (macOS / Linux / Git Bash — Windows: setup.bat)
#
# Tự động toàn bộ:
#   1. Sinh .env từ .env.template (secrets ngẫu nhiên, LORA_DATA_DIR=../lora-data)
#   2. Tạo ../lora-data + tải 4 tile DEM Copernicus GLO-30 (AWS public, ~100 MB)
#   3. docker compose up -d --build  (db → migrate → api + ml + celery + cache)
#   4. Train model Stage 2 ExtraTrees trong container (từ CSV đã commit)
#   5. npm install + khởi động web dev server (nền)
#
# Idempotent: chạy lại an toàn — .env/DEM/model đã có thì giữ nguyên.
# Yêu cầu cài sẵn: Docker (đang chạy) + compose v2, Node ≥ 22, curl, openssl.
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\n\033[1;36m[setup]\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m[setup] LỖI:\033[0m %s\n' "$*" >&2; exit 1; }

# ── 0. Preflight ──────────────────────────────────────────────────────
say "Bước 0/6 — kiểm tra công cụ"
command -v docker  >/dev/null || die "Chưa cài Docker. Cài Docker Desktop (Win/mac) hoặc Docker Engine (Linux)."
docker info        >/dev/null 2>&1 || die "Docker daemon chưa chạy. Mở Docker Desktop rồi chạy lại."
docker compose version >/dev/null 2>&1 || die "Cần Docker Compose v2 (lệnh 'docker compose')."
command -v curl    >/dev/null || die "Thiếu curl."
command -v openssl >/dev/null || die "Thiếu openssl (Git Bash/macOS/Linux có sẵn)."
HAS_NODE=1
command -v npm >/dev/null || { HAS_NODE=0; echo "  ⚠ Không thấy npm — sẽ bỏ qua frontend (cài Node >= 22 rồi chạy lại)."; }

# ── 1. .env ───────────────────────────────────────────────────────────
say "Bước 1/6 — cấu hình .env"
if [ -f .env ]; then
  echo "  .env đã tồn tại — giữ nguyên (xoá file nếu muốn sinh lại)."
else
  cp .env.template .env
  PGPW=$(openssl rand -hex 16)
  JWT=$(openssl rand -base64 48 | tr -d '\n=' | tr '+/' '-_')
  FERNET=$(openssl rand -base64 32 | tr -d '\n' | tr '+/' '-_')
  sed -i.bak \
    -e "s|change_me_in_production|${PGPW}|g" \
    -e "s|^JWT_SECRET=.*|JWT_SECRET=${JWT}|" \
    -e "s|^LINKING_FERNET_KEYS=.*|LINKING_FERNET_KEYS=${FERNET}|" \
    -e "s|^LORA_DATA_DIR=.*|LORA_DATA_DIR=../lora-data|" \
    -e "s|^STAGE2_PREDICT_BASE_URL=.*|STAGE2_PREDICT_BASE_URL=http://ml-service:8001|" \
    .env
  rm -f .env.bak
  # Đường dẫn model Stage 2 trong container ml-service (template không có sẵn).
  printf '\n# Model Stage 2 (setup.sh train trong container, xem README)\nLORA_ML_MODEL_PATH=/app/data/extra_trees_model.joblib\n' >> .env
  echo "  Đã sinh .env (secrets ngẫu nhiên, Stage 2 bật sẵn)."
fi

# ── 2. lora-data + DEM ───────────────────────────────────────────────
say "Bước 2/6 — dữ liệu địa hình (../lora-data)"
mkdir -p ../lora-data/dem ../lora-data/dem-surface
# 4 tile Copernicus GLO-30 phủ Đà Nẵng + phụ cận (bucket AWS public, không cần key).
# crc-covlib tự dò tile theo bbox nên chỉ cần nằm trong thư mục dem/.
DEM_BASE="https://copernicus-dem-30m.s3.amazonaws.com"
for t in N15_00_E107_00 N15_00_E108_00 N16_00_E107_00 N16_00_E108_00; do
  name="Copernicus_DSM_COG_10_${t}_DEM"
  out="../lora-data/dem/${name}.tif"
  if [ -s "$out" ]; then
    echo "  ${name}.tif — đã có, bỏ qua."
  else
    echo "  Tải ${name}.tif ..."
    curl -fL --retry 3 -o "$out" "${DEM_BASE}/${name}/${name}.tif" \
      || die "Tải DEM thất bại (${name}). Kiểm tra mạng rồi chạy lại."
  fi
done

# ── 3. Docker stack ──────────────────────────────────────────────────
say "Bước 3/6 — build + khởi động backend (lần đầu có thể mất vài phút)"
docker compose up -d --build
echo "  Chờ api-service healthy..."
ok=0
for _ in $(seq 1 100); do
  if curl -sf http://localhost:8000/healthz >/dev/null 2>&1; then ok=1; break; fi
  sleep 3
done
[ "$ok" = 1 ] || { docker compose logs --tail 30 api-service; die "api-service không lên được — xem log phía trên."; }
echo "  api-service OK (http://localhost:8000)."

# ── 4. Train model Stage 2 ───────────────────────────────────────────
say "Bước 4/6 — model ML Stage 2 (ExtraTrees)"
if [ -s services/ml-service/data/extra_trees_model.joblib ]; then
  echo "  Model đã có — bỏ qua train."
else
  echo "  Train từ CSV đã commit (chạy trong container, ~1-2 phút)..."
  docker compose run --rm --no-deps celery-worker \
    python services/ml-service/scripts/train_extra_trees.py \
    || die "Train model thất bại — hệ vẫn chạy được Stage 1-only; xem services/ml-service/README.md."
  docker compose restart ml-service >/dev/null
  echo "  Model sẵn sàng — predict sẽ trả stage1+stage2."
fi

# ── 5. Frontend ──────────────────────────────────────────────────────
say "Bước 5/6 — frontend"
if [ "$HAS_NODE" = 1 ]; then
  npm install
  if [ "${SETUP_SKIP_FE_START:-0}" != 1 ]; then
    nohup npm run dev:web > .vite-dev.log 2>&1 &
    echo $! > .vite-dev.pid
    echo "  Vite dev server chạy nền (log: .vite-dev.log). Dừng: kill \$(cat .vite-dev.pid)"
  fi
else
  echo "  Bỏ qua (thiếu npm)."
fi

# ── 6. Xong ──────────────────────────────────────────────────────────
say "Bước 6/6 — HOÀN TẤT ✅"
cat <<'EOF'

  Web:  http://localhost:5173        API: http://localhost:8000/docs

  Các bước tiếp theo (trên web):
  1. Đăng ký tài khoản — tài khoản ĐẦU TIÊN tự động là ADMIN.
  2. Menu "Nguồn dữ liệu" → Liên kết nguồn (lpwanmapper / ChirpStack)
     → "Tải dữ liệu mới nhất" để kéo gateway + điểm đo của bạn về.
  3. Trang "Quản trị" → duyệt batch đóng góp (Duyệt cả file)
     → gateway được kích hoạt + điểm đo lên bản đồ, predict hoạt động.

  Chưa có nguồn dữ liệu riêng? Bản đồ chế độ "estimate" (heatmap tĩnh)
  vẫn xem được ngay; predict cần ít nhất 1 gateway (qua bước 2-3).

EOF
