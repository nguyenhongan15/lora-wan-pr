@echo off
REM Mo 4 terminal cho demo lora-coverage:
REM   1) Vite (FE)        2) Tunnel demo (api + demo)
REM   3) Tunnel realtime  4) Fanout proxy (ChirpStack webhook fan-out)
REM
REM Tien dieu kien: Docker Desktop dang chay va `docker compose up -d`
REM da xong (stack api-service + db + cache + celery + ml-service healthy).
REM Kiem tra: curl http://127.0.0.1:8000/healthz

start "Vite (FE)" cmd /k "cd /d E:\DATN\lora-coverage\apps\web-app && npm run dev"

start "Tunnel demo (api+demo)" cmd /k "cd /d E:\DATN && cloudflared.exe tunnel run lora-estimate-map"

start "Tunnel realtime (ChirpStack)" cmd /k "cd /d E:\DATN && cloudflared.exe tunnel --config C:\Users\Windows\.cloudflared\config-realtime.yml run lora-realtime"

start "Fanout proxy" cmd /k "cd /d E:\DATN\lora-coverage && uv run scripts/chirpstack_fanout.py"
