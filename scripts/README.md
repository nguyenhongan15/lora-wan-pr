# scripts/ — chỉ mục theo nhóm

Thư mục công cụ vận hành + ML + tích hợp. **Để phẳng (không subfolder) có chủ đích**:
nhóm 1–2 bị gọi bằng **path cứng** `scripts/<tên>.py` (Celery task, docker-compose) và
hầu hết script định vị repo qua `REPO_ROOT = Path(__file__).parent.parent`. Đổi tên hoặc
chuyển vào thư mục con sẽ **vỡ đường dẫn** → chỉ sửa khi cập nhật đồng bộ mọi nơi gọi.

> Phân loại để DỄ QUẢN LÝ, không phải để gợi ý chuyển thư mục. Cột "Gọi bởi" cho biết
> cái nào tự động (đừng đụng) vs chạy tay.

---

## 1. ML retrain pipeline — Celery tự gọi ⚠️ path cố định

| Script | Vai trò | Gọi bởi |
|---|---|---|
| `build_training_csv.py` | Build CSV train từ `ts.survey_training` + DEM/landuse, gán cột `data_split` (H3) | `tasks/retrain_ml.py` (bước 1) |
| `eval_extra_trees_holdout.py` | Eval H3 spatial hold-out → val/test metrics | `tasks/retrain_ml.py` (bước 3) |
| `render_ml_report.py` | Render báo cáo Word retrain (dùng `templates/ml_report.html.j2`) | `tasks/retrain_ml.py` (bước 4) |
| `templates/ml_report.html.j2` | Template HTML cho `render_ml_report.py` | — |

> ℹ️ **`train_extra_trees.py` đã chuyển vào** `services/ml-service/scripts/train_extra_trees.py` (train thuộc về ml-service). `tasks/retrain_ml.py` bước 2 gọi nó qua `/app/services/ml-service/scripts/`.

## 2. Coverage / heatmap — Celery/API tự gọi ⚠️ path cố định

| Script | Vai trò | Gọi bởi |
|---|---|---|
| `precompute_rssi_heatmap.py` | Sinh GeoJSON heatmap RSSI (P.1812 + DTM + per-gw NF + survey overlay) | `tasks/rebuild_coverage.py`, web-app |

## 3. Asset builders — địa hình / landuse (chạy tay, tạo asset 1 lần)

| Script | Vai trò |
|---|---|
| `build_dsm.py` | Build DSM raster từ DTM + canopy/built-up cho sample P.1812 |
| `build_dsm_built_up_only.py` | Biến thể DSM: chỉ giữ building ở pixel built-up (ESA WorldCover 50), tránh artifact canopy rural |
| `fetch_osm_landuse.py` | Tải landuse OSM → GeoJSON cho `/app/osm` (runtime landuse lookup) |
| `extract_landuse_central_vn.py` | Trích landuse central VN từ PBF → `data/training/terrain/landuse_central.geojson` |

## 4. Gateway & Database ops (chạy tay, idempotent)

| Script | Vai trò |
|---|---|
| `seed_gateways.py` | Seed `geo.gateways` từ metadata thật (ON CONFLICT DO UPDATE) |
| `reverse_geocode_gateways.py` | Reverse-geocode toạ độ gateway qua Nominatim |
| `backfill_gateway_noise_floor.py` | Backfill `noise_floor_dbm` = median(rssi − snr) theo train window |
| `backfill_provenance.py` | Fixup cột provenance (external_id…) cho data legacy trước sync |
| `backfill_rdt.py` | Replay uplink ChirpStack từ `r-dt/*.json` → `ts.survey_quarantine` |
| `backup_db.sh` | Backup Postgres (xem `DEPLOY.md`) |

## 5. ChirpStack / LPWAN Mapper integration (chạy tay)

| Script | Vai trò |
|---|---|
| `chirpstack_fanout.py` | Fan-out uplink ChirpStack (dùng trong `start-demo.bat`) |
| `sync_one_cli.py` | CLI demo pull 1 lần từ lpwanmapper → upsert DB |
| `lpwanmapper_smoke.py` | Smoke test kết nối lpwanmapper (`.env.lpwanmapper.local`) |
| `probe_chirpstack_gateway_state.py` | One-shot probe `ListGateways` → last_seen_at + state |

## 6. Đánh giá / kiểm chứng / smoke (phân tích thủ công, không vận hành)

| Script | Vai trò |
|---|---|
| `eval_extra_trees.py` | Eval ET vs XGBoost thủ công (report kiểu `*-train/`) |
| `eval_api_predict_holdout.py` | Eval qua HTTP `/coverage/predict` → đo accuracy serve-side (gap vs offline) |
| `validate_stage1_itu.py` | Validate Stage 1 P.1812 + P.2108 trên test hold-out |
| `verify_reference_module.py` | Kiểm chứng feature terrain/Fresnel/landuse vs giá trị CSV |
| `smoke_admin_auto_approve.py` | Smoke test luồng admin self-contribution auto-approve |

## 7. Stage 2 XGBoost residual — LEGACY (đã chuyển `archive/`)

Toàn bộ dòng XGBoost residual đã dời sang `archive/` (local-only): script
`train_residual_model.py`, `retrain_stage2.sh` + artifact `stage2_xgb.joblib(.v03backup)`.
Model production hiện tại là **ExtraTrees end-to-end** (nhóm 1). Để rollback XGBoost:
copy joblib từ `archive/` về `services/ml-service/data/` rồi trỏ `LORA_ML_MODEL_PATH`.

> Lưu ý: thư viện `xgboost` vẫn cần (dep) vì `eval_extra_trees.py` (nhóm 6) train
> XGBoost on-the-fly để so sánh với ExtraTrees.

---

### Ghi chú quản lý
- Đã chuyển sang `archive/` (local-only, gitignore): `scripts/experiments/` (spike/debug
  R&D), 3 script sinh tài liệu đồ án (`draw_hinh_4_1.py`, `export_chuong_ml.py`,
  `gen_ml_pipeline_report.py`), và dòng XGBoost residual (`train_residual_model.py`,
  `retrain_stage2.sh`).
- `__pycache__/` là bytecode rác, tự sinh lại.
