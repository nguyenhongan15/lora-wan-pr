# web-app

React 19 + Vite 8 + **JavaScript ES2024** + Tailwind 4 + TanStack Query + Zod.

> Theo `core-logic/main-logic/system-architecture.md` §2.1 / §3.1: ngôn ngữ là JavaScript ES2024 với JSDoc + `// @ts-check`. Không có TypeScript build step. Type-safety ở runtime do Zod đảm nhiệm.

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

## Vertical slice v1

1 page form: nhập lat/lng/SF → POST `/api/v1/coverage/predict` → hiển thị RSSI, SNR, coverage status, confidence, model version.

## Các bước tiếp theo (chưa làm)

- shadcn/ui (JS variants) + Radix primitives
- Mapbox GL JS / MapLibre map view với coverage layer
- Survey upload UI
- Auth flow (OAuth2 / JWT)
