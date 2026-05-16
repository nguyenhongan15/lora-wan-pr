# web-app

React 19 + Vite 8 + **JavaScript ES2024** + Tailwind 4 + TanStack Query + Zod.

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




