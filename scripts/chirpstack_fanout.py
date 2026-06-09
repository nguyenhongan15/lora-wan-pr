"""ChirpStack fan-out proxy — nhận 1 POST từ ChirpStack, forward cả vào
api-service (real-time) và api.lpwanmapper.com (giữ pipeline backup).

ChirpStack v4 chỉ cho 1 HTTP Integration / app, nên script này thay vai
"ChirpStack endpoint" để fan-out tới 2 destination thực.

Run (uv tự cài fastapi/uvicorn/httpx vào virtualenv tạm):
    uv run scripts/chirpstack_fanout.py

Env (override khi cần):
    FANOUT_PORT       (default 9000)        — port local cloudflared trỏ vào
    FANOUT_API_BASE   (default http://127.0.0.1:8000) — api-service base
    FANOUT_LPWAN_URL  (default URL của BIGBOSS)      — empty = skip lpwanmapper

ChirpStack POST → /api/v1/webhooks/chirpstack/source/<token>
  → mirror tới  {FANOUT_API_BASE}/api/v1/webhooks/chirpstack/source/<token>
  → mirror tới  FANOUT_LPWAN_URL (URL cố định)
Trả 202 cho ChirpStack bất kể downstream OK/fail (ChirpStack có retry).
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["fastapi", "uvicorn", "httpx"]
# ///

from __future__ import annotations

import asyncio
import logging
import os

import httpx
from fastapi import FastAPI, Request, Response

API_BASE = os.environ.get("FANOUT_API_BASE", "http://127.0.0.1:8000").rstrip("/")
LPWAN_URL = os.environ.get(
    "FANOUT_LPWAN_URL",
    "https://api.lpwanmapper.com/webhook/vanlic-dn",
)
PORT = int(os.environ.get("FANOUT_PORT", "9000"))

log = logging.getLogger("fanout")

app = FastAPI()


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "api_base": API_BASE, "lpwan_configured": bool(LPWAN_URL)}


@app.post("/{full_path:path}")
async def fanout(full_path: str, request: Request) -> Response:
    body = await request.body()
    ct = request.headers.get("content-type", "application/json")
    qs = request.url.query
    suffix = f"/{full_path}" + (f"?{qs}" if qs else "")

    targets: list[tuple[str, str]] = [("api-service", f"{API_BASE}{suffix}")]
    if LPWAN_URL:
        targets.append(("lpwanmapper", LPWAN_URL))

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        results = await asyncio.gather(
            *(client.post(url, content=body, headers={"content-type": ct}) for _, url in targets),
            return_exceptions=True,
        )

    for (name, _url), result in zip(targets, results, strict=True):
        if isinstance(result, Exception):
            log.warning("forward → %s FAILED: %s", name, result)
        else:
            log.info("forward → %s HTTP %d", name, result.status_code)

    return Response(status_code=202)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
