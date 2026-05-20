# Deploy & Rollback

Pre-deploy checklist §9 ("Rollback Strategy") — minimal viable cho 1-VPS single-stack.
Không phải blue-green thật (cần 2 host + LB) nhưng đủ "tested rollback path":
image cũ vẫn trên disk → revert là 1 lệnh `docker compose up -d`.

## Build & deploy

```bash
# Pin image tag bằng git SHA — không bao giờ dùng `latest` cho prod.
export IMAGE_TAG=$(git rev-parse --short HEAD)

# Build image với tag SHA (compose dùng cùng tag cho api-service + migrate).
docker compose build api-service

# Run migrate (1 lần) → up api-service.
docker compose up -d
```

`IMAGE_TAG` rỗng → fallback `dev` (dev local).
Compose `image:` field giữ tag — image cũ tag SHA trước KHÔNG bị overwrite.

## Smoke test sau deploy

```bash
# 1. Healthz
curl -fsS http://localhost:8000/healthz

# 2. Auth round-trip (cookie + access token)
curl -fsS -X POST http://localhost:8000/api/v1/auth/login \
    -H "content-type: application/json" \
    -d '{"email":"smoke@example.com","password":"<known>"}'

# 3. Metrics scrape
curl -fsS http://localhost:8000/metrics | grep http_requests_total | head
```

3 cái pass → deploy ok. Fail bất kỳ → rollback ngay (xem dưới).

## Rollback

Khi smoke fail / error spike / latency tăng đột biến:

```bash
# 1. Tìm SHA prod đang chạy ngon (commit trước cái vừa deploy).
git log --oneline -n 10

# 2. Set IMAGE_TAG sang SHA cũ + up lại — KHÔNG build (image cũ vẫn còn).
export IMAGE_TAG=<prev-sha>
docker compose up -d --no-build api-service
```

Container restart trong < 5s vì image đã có sẵn trên disk.

### Migration rollback (cần thiết khi)

Migration mới đã chạy (alembic upgrade head) NHƯNG code mới lỗi → code cũ
không hiểu schema mới → bắt buộc downgrade DB trước khi revert image:

```bash
# 1. Tìm alembic revision của code cũ (trong migrations/versions/).
docker compose exec migrate python -m alembic -c migrations/alembic.ini current

# 2. Downgrade 1 step (hoặc tới revision cụ thể).
docker compose exec migrate python -m alembic -c migrations/alembic.ini \
    downgrade -1

# 3. Revert image theo lệnh trên.
```

**Lưu ý:** Một số migration không safe để downgrade (vd DROP COLUMN sau khi
backfill). Mỗi migration mới PHẢI review:
- `op.downgrade()` có thực sự undo được không?
- Có data destructive không?

Migrations đã review/ack được destructive → ghi vào docstring đầu file.

## Image retention

Disk hosting nhiều image. Giữ:
- 3 image gần nhất (current + 2 prev) cho rollback ladder.
- Image > 30 ngày: prune.

```bash
docker image ls lora-wan-api --format '{{.Tag}} {{.CreatedSince}}' | sort
docker image prune -a --filter "until=720h" --filter "label!=keep"
```

## Monitoring (Prometheus + alerts)

api-service expose `/metrics` (xem `edge/metrics.py` — 4 golden signals
+ F2 lookup SLO histogram). Alert rules: `ops/prometheus/alerts.yml`.

### Wire-up (host monitoring)

```bash
# 1. Copy rules + scrape config sang host Prometheus.
sudo cp ops/prometheus/alerts.yml /etc/prometheus/rules/api-service.yml
sudo cp ops/prometheus/prometheus.yml.example /etc/prometheus/prometheus.yml

# 2. Reload Prometheus (HUP hoặc /-/reload nếu enable lifecycle API).
sudo systemctl reload prometheus
# hoặc: curl -X POST http://localhost:9090/-/reload

# 3. Validate rule syntax trước reload (optional nhưng nên).
promtool check rules /etc/prometheus/rules/api-service.yml

# 4. Kiểm tra rules loaded.
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[].name'
```

`/metrics` KHÔNG được expose public — chỉ Prometheus trong private
network scrape. Ingress (nginx / Cloudflare Tunnel) phải block path
`/metrics` ở edge. Nếu chạy Prometheus cùng VPS → scrape qua docker
network (`api-service:8000`).

### Alert severity

- `severity: page` → wake oncall ngay (5xx >2%, SLO P95 violation,
  service down, error-budget burn).
- `severity: ticket` → next business day (latency drift, saturation
  soft signal, 5xx burst nhỏ).

Alertmanager routing config tách riêng — không trong repo này.

## Khi chuyển sang blue-green thật

Mốc trigger: traffic > 50 rps sustained HOẶC SLA contractually ≤ 99.9%.
Lúc đó single-VPS không đủ — cần 2 host + LB (Cloudflare Tunnel / Caddy /
nginx upstream weighted). Spec viết khi sang.
