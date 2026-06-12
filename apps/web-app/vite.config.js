import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    // Cloudflare Tunnel forward demo.lora-estimate-map.uk → localhost:5173.
    // Vite mặc định chặn host lạ (Host header check) — phải whitelist subdomain.
    allowedHosts: ["demo.lora-estimate-map.uk"],
  },
  build: {
    target: "es2022",
    sourcemap: true,
  },
});
