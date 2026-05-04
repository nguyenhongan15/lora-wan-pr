# Import LPWAN Data

Scripts để import dữ liệu thật từ `lpwanmapper.com` vào DB (thay thế seed data).

## 📂 Cấu trúc

```
backend/
├── data/lpwan/                       ← file JSON từ lpwanmapper
│   ├── response_get_data.json       (metadata: 11 gateways + 3 device names)
│   ├── response_devices_latest.json (3 device records mới nhất)
│   └── response_data.json           (10k records đầy đủ)
│
└── scripts/
    ├── cleanup_seed.sql              (dọn seed data cũ)
    ├── lpwan_bootstrap.py            (tạo project/gateway/device/campaign)
    └── lpwan_import.py               (import 10k measurements)
```

## 🚀 Cách chạy (3 bước)

### Bước 1: Dọn seed data cũ

Mở pgAdmin (http://localhost:5050) → connect DB `lora_coverage` → Query Tool → paste nội dung `scripts/cleanup_seed.sql` → F5.

Hoặc chạy từ terminal:

```powershell
# Windows PowerShell — đảm bảo docker đang chạy
docker exec -i lora_postgres psql -U lora_user -d lora_coverage < scripts/cleanup_seed.sql
```

### Bước 2: Bootstrap (tạo project/gateways/devices/campaigns)

```powershell
docker exec -it lora_api python scripts/lpwan_bootstrap.py
```

Output kỳ vọng:
```
📂 Loaded: 11 gateways, 3 latest records

🚀 Bootstrap DB from lpwanmapper data...
  [insert] project: LoRa Da Nang Coverage
  gateways: +11 inserted, 0 skipped
  devices: +3 inserted, 0 skipped
  campaigns: +4 inserted, 0 skipped

✅ Bootstrap xong!
```

### Bước 3: Import 10k measurements

```powershell
docker exec -it lora_api python scripts/lpwan_import.py response_data.json
```

Output kỳ vọng (mất ~1-3 phút):
```
📂 Loading response_data.json...
   → 10008 records

🚀 Import vào DB...
   → DB có 3 devices, 11 gateways

📊 Kết quả:
   ├─ Total records:        10008
   ├─ Inserted:            ~7300  ✓  (mỗi record có 1-3 rxInfo)
   ├─ Skip: no GPS         ~2700
   ├─ Skip: no device      0
   ├─ Skip: no gateway     0
   └─ Skip: duplicate      0

✅ Done!
```

## 🔍 Verify sau khi import

### Qua API:
```bash
# Danh sách 4 campaigns
curl http://localhost:8000/api/v1/campaigns/

# Stats của Tháng 1/2026
curl "http://localhost:8000/api/v1/measurements/stats?campaignId=c0000000-0000-0000-0000-000000000001"
```

### Qua pgAdmin:
```sql
-- Mỗi campaign có bao nhiêu measurement?
SELECT c.name, COUNT(m.id) AS measurements
FROM campaigns c
LEFT JOIN measurements m ON m.campaign_id = c.id AND m.deleted_at IS NULL
GROUP BY c.id, c.name
ORDER BY c.start_date;

-- Phân bố RSSI theo SF
SELECT spreading_factor, COUNT(*), 
       ROUND(AVG(rssi_dbm)::numeric, 1) AS avg_rssi,
       ROUND(AVG(snr_db)::numeric, 1) AS avg_snr
FROM measurements 
WHERE deleted_at IS NULL
GROUP BY spreading_factor
ORDER BY spreading_factor;
```

### Qua Frontend:
1. Mở `http://localhost:5173`
2. Dropdown "Campaign" → chọn "Data 2026-01" (hoặc tháng khác)
3. Scatter points hiện khắp Đà Nẵng
4. StatsPanel hiện total + avg RSSI/SNR
5. Bấm "Chạy ML IDW" → sinh heatmap prediction

## ⚠️ Lưu ý

- **GPS = 0 bị skip** (device chưa có fix GPS): ~27% số record. Đây là bình thường.
- **Mỗi record có 1-3 rxInfo** (1 packet được nhiều gateway nhận) → số measurement thường > số record.
- **Dedup**: nếu chạy lại, dedup check (device, gateway, fCnt, time) tránh duplicate.
- **Môi trường**: toàn bộ campaigns đang set `environment_type = 'urban'`. Có thể sửa trong pgAdmin nếu muốn phân biệt.

## 🔄 Khi có data mới từ lpwanmapper

Cách 1 — Download JSON mới từ lpwanmapper, Đặt vào backend/data/lpwan/   rồi chạy lại script:
```powershell
# Replace file response_data.json
docker exec -it lora_api python scripts/lpwan_import.py response_data_new.json
```

Cách 2 — Dùng endpoint `/api/v1/sync/*` trong backend để pull real-time (tôi sẽ fix sau nếu bạn cần).
