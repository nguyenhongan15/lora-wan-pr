# web-app

React 19 + Vite 8 + **JavaScript ES2024** (JSDoc + Zod runtime) + Tailwind 4 + TanStack Query + MapLibre GL.

## Chạy local

```bash
cp .env.example .env       # chỉnh nếu API ở host khác
npm install                # ở root để hydrate workspace
npm --workspace apps/web-app run dev    # http://localhost:5173
```

Yêu cầu: api-service chạy ở `VITE_API_BASE_URL` (mặc định http://localhost:8000).

## Scripts

| Script | Mô tả |
|---|---|
| `npm run dev` | Vite dev server, port 5173 |
| `npm run build` | Build production bundle |
| `npm run lint` | ESLint 9 (flat config, không dùng typescript-eslint) |
| `npm run jsdoc-check` | `tsc -p jsconfig.json` — kiểm tra JSDoc bằng `--checkJs` |

## Coverage map modes

Component `CoverageMap.jsx` có 4 view mode (chuyển qua dropdown trong tab "Bản đồ phủ sóng"):

| Mode | Source data | Mô tả |
|---|---|---|
| `points` | API `/coverage/survey` | Survey điểm đo raw (mỗi point 1 marker) |
| `heatmap` | Computed client-side | Density heatmap từ survey points |
| `minsf` | `public/coverage/minsf/*.geojson` | Min spreading factor per gateway (Stage 1 ITU + walk-survey bias) |
| `estimate` 🆕 | `public/coverage/rssi/*.geojson` | Composite RSSI max qua 13 gateway (Stage 1 + Stage 2 XGBoost) |

### Static coverage data

Pre-computed GeoJSON ship cùng frontend:

```
public/coverage/
  minsf/
    <gw_code>.geojson        # 11 file, mỗi gw 1 layer (4 SF bands)
    bias_<gw_code>.json      # Walk-survey calibration table per gw
    manifest.json            # Index + metadata (generated_at, version)
  rssi/
    composite.geojson        # Max RSSI composite (4 bins)
    redundancy.geojson       # gw_count per cell (3 bins)
    manifest.json            # Stage 1+2 model version, bbox, generated_at
```

Re-generate khi gw catalog hoặc Stage 1/2 đổi:
```bash
docker exec lora-wan-api uv run python scripts/precompute_minsf.py --bbox danang
docker exec lora-wan-api uv run python scripts/precompute_rssi_heatmap.py --bbox danang
# Copy output ra apps/web-app/public/coverage/
```

## i18n

`src/i18n/strings.js` chứa toàn bộ string Việt (block: `coverageStatus`, `coverageMap`, `minsf`, `estimate`, `auth`, `admin`, ...). Không hardcode string trong component.


