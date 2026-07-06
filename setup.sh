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

# ── 0. Công cụ — kiểm tra, THIẾU THÌ TỰ CÀI ───────────────────────────
# Windows: winget (App Installer, có sẵn Win 10/11) · macOS: Homebrew
# (tự cài nếu thiếu) · Linux: apt/dnf/yum/pacman/zypper + get.docker.com.
# Docker Desktop lần đầu vẫn cần bạn bấm chấp nhận điều khoản trong cửa
# sổ hiện ra — script tự mở và chờ daemon lên.
say "Bước 0/6 — kiểm tra công cụ (thiếu sẽ tự cài)"

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
