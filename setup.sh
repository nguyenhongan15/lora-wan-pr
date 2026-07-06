#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# LoRa Coverage Platform — setup 1 lệnh cho máy mới (fresh clone).
#
#   ./setup.sh          (macOS / Linux / Git Bash — Windows: setup.bat)
#
# Tự động toàn bộ:
#   0. Kiểm tra công cụ (Git / Docker / Node >= 22) — THIẾU THÌ TỰ CÀI
#   1. Sinh .env từ .env.template (secrets ngẫu nhiên, LORA_DATA_DIR=../lora-data)
#   2. Tạo ../lora-data + tải 4 tile DEM Copernicus GLO-30 (AWS public, ~100 MB)
#   3. docker compose up -d --build  (db → migrate → api + ml + celery + cache)
#   4. Train model Stage 2 ExtraTrees trong container (từ CSV đã commit)
#   5. Dữ liệu địa lý đầy đủ trong container: merge DEM thành
#      copernicus_glo30_danang.tif (đúng tên retrain ML cần) + tải OSM PBF
#      (~350 MB) + build DSM (rebuild heatmap). Bỏ qua: SETUP_SKIP_DSM=1
#   6. npm install + khởi động web dev server (nền)
#
# Idempotent: chạy lại an toàn — .env/DEM/PBF/DSM/model đã có thì giữ nguyên.
# Không cần cài sẵn gì ngoài trình terminal chạy được bash (Windows: Git Bash).
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\n\033[1;36m[setup]\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m[setup] LỖI:\033[0m %s\n' "$*" >&2; exit 1; }

# ── 0. Công cụ — kiểm tra, THIẾU THÌ TỰ CÀI ───────────────────────────
# Windows: winget (App Installer, có sẵn Win 10/11) · macOS: Homebrew
# (tự cài nếu thiếu) · Linux: apt/dnf/yum/pacman/zypper + get.docker.com.
# Docker Desktop lần đầu vẫn cần bạn bấm chấp nhận điều khoản trong cửa
# sổ hiện ra — script tự mở và chờ daemon lên.
say "Bước 0/7 — kiểm tra công cụ (thiếu sẽ tự cài)"

OS=linux
case "$(uname -s)" in
  Darwin) OS=mac ;;
  MINGW*|MSYS*|CYGWIN*) OS=windows ;;
esac

SUDO=""
if [ "$OS" = linux ] && [ "$(id -u)" != 0 ]; then
  command -v sudo >/dev/null || die "Cần root hoặc sudo để tự cài công cụ trên Linux."
  SUDO="sudo"
fi

pkg_install() {  # Linux: cài gói qua package manager phát hiện được
  if   command -v apt-get >/dev/null; then $SUDO apt-get update -qq && $SUDO apt-get install -y "$@"
  elif command -v dnf     >/dev/null; then $SUDO dnf install -y "$@"
  elif command -v yum     >/dev/null; then $SUDO yum install -y "$@"
  elif command -v pacman  >/dev/null; then $SUDO pacman -Sy --noconfirm "$@"
  elif command -v zypper  >/dev/null; then $SUDO zypper install -y "$@"
  else die "Không nhận diện được package manager — cài thủ công: $*"
  fi
}

winget_install() {
  WINGET=$(command -v winget || command -v winget.exe || true)
  [ -n "$WINGET" ] || die "Thiếu winget (App Installer — cập nhật Windows 10/11 từ Microsoft Store) — hoặc cài thủ công: $1"
  "$WINGET" install --id "$1" -e --silent \
    --accept-package-agreements --accept-source-agreements \
    || die "winget cài $1 thất bại — cài thủ công rồi chạy lại ./setup.sh"
}

brew_ensure() {
  command -v brew >/dev/null && return 0
  say "Cài Homebrew (có thể hỏi mật khẩu máy)..."
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
    || die "Cài Homebrew thất bại — xem https://brew.sh rồi chạy lại."
  eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
}

refresh_windows_path() {
  # App vừa cài bằng winget chưa có trong PATH của shell đang chạy.
  local p
  for p in "/c/Program Files/Git/bin" "/c/Program Files/nodejs" \
           "/c/Program Files/Docker/Docker/resources/bin"; do
    [ -d "$p" ] && PATH="$PATH:$p"
  done
  export PATH
}

ensure_basics() {
  command -v curl >/dev/null || { [ "$OS" = linux ] && pkg_install curl || die "Thiếu curl."; }
  command -v openssl >/dev/null || { [ "$OS" = linux ] && pkg_install openssl || die "Thiếu openssl."; }
}

ensure_git() {
  command -v git >/dev/null && return 0
  say "Thiếu Git — đang cài..."
  case "$OS" in
    windows) winget_install Git.Git; refresh_windows_path ;;
    mac)     brew_ensure; brew install git ;;
    linux)   pkg_install git ;;
  esac
  command -v git >/dev/null || die "Git chưa sẵn sàng sau khi cài — mở terminal mới rồi chạy lại ./setup.sh"
}

node_major() { node -v 2>/dev/null | sed 's/^v\([0-9]*\).*/\1/'; }
node_ok() { command -v node >/dev/null && [ "$(node_major)" -ge 22 ] 2>/dev/null; }

ensure_node() {
  node_ok && return 0
  if command -v node >/dev/null; then
    say "Node $(node -v) < 22 — cài bản 22 LTS..."
  else
    say "Thiếu Node.js — đang cài bản 22 LTS..."
  fi
  case "$OS" in
    windows) winget_install OpenJS.NodeJS.LTS; refresh_windows_path ;;
    mac)     brew_ensure; brew install node ;;
    linux)
      if command -v apt-get >/dev/null; then
        curl -fsSL https://deb.nodesource.com/setup_22.x | $SUDO bash - \
          && $SUDO apt-get install -y nodejs
      elif command -v dnf >/dev/null || command -v yum >/dev/null; then
        curl -fsSL https://rpm.nodesource.com/setup_22.x | $SUDO bash - \
          && pkg_install nodejs
      else
        pkg_install nodejs npm
      fi ;;
  esac
  node_ok || die "Node >= 22 chưa sẵn sàng sau khi cài — mở terminal MỚI rồi chạy lại ./setup.sh"
}

docker_daemon_wait() {
  local i
  for i in $(seq 1 60); do
    docker info >/dev/null 2>&1 && return 0
    sleep 5
  done
  return 1
}

ensure_docker() {
  if ! command -v docker >/dev/null; then
    say "Thiếu Docker — đang cài..."
    case "$OS" in
      windows) winget_install Docker.DockerDesktop; refresh_windows_path ;;
      mac)     brew_ensure; brew install --cask docker ;;
      linux)
        curl -fsSL https://get.docker.com | $SUDO sh || die "Cài Docker Engine thất bại — xem https://docs.docker.com/engine/install/"
        $SUDO systemctl enable --now docker 2>/dev/null || true
        if [ -n "$SUDO" ] && ! docker info >/dev/null 2>&1; then
          $SUDO usermod -aG docker "$USER" 2>/dev/null || true
          say "Đã thêm '$USER' vào nhóm docker — ĐĂNG XUẤT rồi đăng nhập lại (hoặc chạy 'newgrp docker'), sau đó chạy ./setup.sh lần nữa để tiếp tục."
          exit 0
        fi ;;
    esac
  fi
  if ! docker info >/dev/null 2>&1; then
    case "$OS" in
      windows)
        say "Khởi động Docker Desktop (lần đầu: bấm chấp nhận điều khoản trong cửa sổ hiện ra)..."
        [ -f "/c/Program Files/Docker/Docker/Docker Desktop.exe" ] \
          && "/c/Program Files/Docker/Docker/Docker Desktop.exe" >/dev/null 2>&1 &
        ;;
      mac)
        say "Khởi động Docker Desktop (lần đầu: bấm chấp nhận điều khoản)..."
        open -a Docker 2>/dev/null || true ;;
      linux)
        $SUDO systemctl start docker 2>/dev/null || true ;;
    esac
    echo "  Chờ Docker daemon (tối đa 5 phút)..."
    docker_daemon_wait || die "Docker daemon không lên — mở Docker Desktop thủ công, chờ chạy xong rồi chạy lại ./setup.sh"
  fi
  docker compose version >/dev/null 2>&1 || die "Docker có nhưng thiếu Compose v2 — cập nhật Docker Desktop / cài docker-compose-plugin."
}

ensure_basics
ensure_git
ensure_docker
ensure_node
HAS_NODE=1
echo "  Đủ công cụ: git $(git --version | awk '{print $3}') · docker $(docker --version | awk '{gsub(",","");print $3}') · node $(node -v)"

# ── 1. .env ───────────────────────────────────────────────────────────
say "Bước 1/7 — cấu hình .env"
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
say "Bước 2/7 — dữ liệu địa hình (../lora-data)"
mkdir -p ../lora-data/dem ../lora-data/dem-surface
# Đích cuối là 1 file merge ĐÚNG TÊN copernicus_glo30_danang.tif (pipeline
# retrain build_training_csv.py kỳ vọng tên này) — bước 5 merge trong
# container. Ở đây chỉ tải 4 tile thô Copernicus GLO-30 (AWS public) vào
# dem-raw/; đã có file merge thì bỏ qua toàn bộ.
DEM_MERGED=../lora-data/dem/copernicus_glo30_danang.tif
if [ -s "$DEM_MERGED" ]; then
  echo "  copernicus_glo30_danang.tif — đã có, bỏ qua tải tile thô."
else
  mkdir -p ../lora-data/dem-raw
  # Dọn tile thô từ phiên bản setup cũ từng đặt thẳng trong dem/.
  mv ../lora-data/dem/Copernicus_DSM_COG_10_*_DEM.tif ../lora-data/dem-raw/ 2>/dev/null || true
  DEM_BASE="https://copernicus-dem-30m.s3.amazonaws.com"
  for t in N15_00_E106_00 N15_00_E107_00 N15_00_E108_00 \
           N16_00_E106_00 N16_00_E107_00 N16_00_E108_00; do
    name="Copernicus_DSM_COG_10_${t}_DEM"
    out="../lora-data/dem-raw/${name}.tif"
    if [ -s "$out" ]; then
      echo "  ${name}.tif — đã có, bỏ qua."
    else
      echo "  Tải ${name}.tif ..."
      curl -fL --retry 3 -o "$out" "${DEM_BASE}/${name}/${name}.tif" \
        || die "Tải DEM thất bại (${name}). Kiểm tra mạng rồi chạy lại."
    fi
  done
fi

# ── 3. Docker stack ──────────────────────────────────────────────────
say "Bước 3/7 — build + khởi động backend (lần đầu có thể mất vài phút)"
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
say "Bước 4/7 — model ML Stage 2 (ExtraTrees)"
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

# ── 5. Dữ liệu địa lý hoàn chỉnh: DEM chuẩn tên + OSM PBF + DSM ──────
# Phục vụ 2 luồng nâng cao:
#   * Rebuild "bản đồ ước lượng" (admin/Celery) — cần DSM; thiếu thì
#     fallback DTM + P.2108 (kém chính xác đô thị).
#   * Retrain ML qua admin — build_training_csv.py kỳ vọng ĐÚNG file
#     /data/dem/copernicus_glo30_danang.tif (landuse terrain đã có trong git).
# Tất cả chạy TRONG container worker (image có sẵn geo deps); mount thêm
# ../lora-data ghi-được vì mount /data mặc định read-only. Fail-soft.
say "Bước 5/7 — dữ liệu địa lý cho rebuild heatmap + retrain ML (bỏ qua: SETUP_SKIP_DSM=1)"
if [ "${SETUP_SKIP_DSM:-0}" = 1 ]; then
  echo "  Bỏ qua theo SETUP_SKIP_DSM=1 — heatmap rebuild sẽ fallback DTM + P.2108."
else
  mkdir -p ../lora-data/osm
  # Đường dẫn host TUYỆT ĐỐI cho docker -v. Git Bash: pwd -W trả E:/...;
  # MSYS_NO_PATHCONV=1 để msys không phá chuỗi "host:container".
  LORA_DATA_ABS=$(cd ../lora-data && (pwd -W 2>/dev/null || pwd))
  drun() {
    MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps \
      -v "${LORA_DATA_ABS}:/data-rw" celery-worker "$@"
  }

  # 5a. Merge 6 tile thô → copernicus_glo30_danang.tif. Bounds = ĐO TỪ file
  # gốc trên máy dev (rasterio bounds) — khớp từng pixel để retrain/heatmap
  # cho kết quả như máy gốc.
  if [ -s "$DEM_MERGED" ]; then
    echo "  DEM merge đã có — bỏ qua."
  else
    echo "  Merge tile DEM → copernicus_glo30_danang.tif ..."
    if drun python scripts/merge_dem_tiles.py \
         --src-dir /data-rw/dem-raw \
         --out /data-rw/dem/copernicus_glo30_danang.tif \
         --bounds 106.9465 15.3699 108.7571 16.6288; then
      rm -rf ../lora-data/dem-raw
      echo "  DEM chuẩn sẵn sàng (retrain ML đọc được đúng tên file)."
    else
      echo "  ⚠ Merge DEM thất bại — /predict vẫn chạy bằng tile thô; chạy lại ./setup.sh để thử lại."
      # Giữ tile thô trong dem/ để crc-covlib còn dò được (di chuyển ngược).
      mv ../lora-data/dem-raw/*.tif ../lora-data/dem/ 2>/dev/null || true
    fi
  fi

  # 5b + 5c. OSM PBF + DSM.
  if ls ../lora-data/dem-surface/*.tif >/dev/null 2>&1; then
    echo "  DSM đã có trong ../lora-data/dem-surface — bỏ qua."
  else
    PBF=../lora-data/osm/vietnam-latest.osm.pbf
    if [ -s "$PBF" ]; then
      echo "  OSM PBF đã có — bỏ qua tải."
    else
      echo "  Tải OSM PBF Việt Nam (~350 MB, Geofabrik — vài phút)..."
      drun python scripts/fetch_osm_pbf.py --out /data-rw/osm/vietnam-latest.osm.pbf \
        || die "Tải OSM PBF thất bại — kiểm tra mạng rồi chạy lại ./setup.sh (các bước xong rồi sẽ tự bỏ qua)."
    fi
    echo "  Build DSM từ DEM + nhà OSM (vài phút tới ~30 phút tùy máy)..."
    if drun python scripts/build_dsm.py \
         --dem-dir /data-rw/dem \
         --pbf /data-rw/osm/vietnam-latest.osm.pbf \
         --out-dir /data-rw/dem-surface; then
      echo "  DSM sẵn sàng — /predict + rebuild heatmap chạy surface mode."
    else
      echo "  ⚠ Build DSM thất bại — hệ vẫn chạy (DTM + P.2108); chạy lại ./setup.sh để thử lại."
    fi
  fi
  docker compose restart api-service ml-service >/dev/null
fi

# ── 6. Frontend ──────────────────────────────────────────────────────
say "Bước 6/7 — frontend"
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
say "Bước 7/7 — HOÀN TẤT ✅"
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
