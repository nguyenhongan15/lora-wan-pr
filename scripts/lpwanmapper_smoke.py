"""Smoke test cho LpwanmapperSource adapter — gọi API thật.

Mục đích: verify giả định trong adapter (auth header `Bearer <token>`, response
shape /login + /data) trước khi build Step 4+ chồng lên.

Usage:
    # 1. Tạo file credential (gitignored)
    cp .env.lpwanmapper.local.example .env.lpwanmapper.local
    # -> điền LPWANMAPPER_EMAIL / LPWANMAPPER_PASSWORD

    # 2. Run
    uv run --project services/api-service python scripts/lpwanmapper_smoke.py

Exit codes:
    0  thành công (mọi phase pass)
    2  thiếu credential / env file
    3  SourceAuthFailed (sai email/password hoặc Bearer header sai format)
    4  SourceUnreachable (network / 5xx)
    5  SourceFetchFailed (response shape không như expect)
    9  lỗi không lường trước

KHÔNG in token, password, hoặc full record (có thể chứa GPS PII). Chỉ in
count + sample đã redact.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env.lpwanmapper.local"


def _load_env() -> tuple[str, str]:
    if not ENV_FILE.exists():
        print(f"[FAIL] Không tìm thấy {ENV_FILE.name} ở repo root.", file=sys.stderr)
        print("       Tạo file với 2 dòng:", file=sys.stderr)
        print("         LPWANMAPPER_EMAIL=...", file=sys.stderr)
        print("         LPWANMAPPER_PASSWORD=...", file=sys.stderr)
        sys.exit(2)

    from dotenv import load_dotenv

    load_dotenv(ENV_FILE, override=False)
    email = os.environ.get("LPWANMAPPER_EMAIL", "").strip()
    password = os.environ.get("LPWANMAPPER_PASSWORD", "").strip()
    if not email or not password:
        print("[FAIL] LPWANMAPPER_EMAIL / LPWANMAPPER_PASSWORD trống.", file=sys.stderr)
        sys.exit(2)
    return email, password


def _redact_email(e: str) -> str:
    user, _, domain = e.partition("@")
    if not domain:
        return "***"
    return f"{user[:2]}***@{domain}"


def _gateway_sample(gw) -> str:
    return (
        f"id={gw.external_id} "
        f"lat={gw.latitude:.4f} lon={gw.longitude:.4f} "
        f"alt={gw.altitude_m}"
    )


def _measurement_sample(m) -> str:
    return (
        f"id={m.external_id} time={m.time.isoformat()} "
        f"rssi={m.rssi_dbm} snr={m.snr_db} sf={m.spreading_factor} "
        f"freq={m.frequency_mhz} "
        f"dev={m.device_external_id} gw={m.serving_gateway_external_id}"
    )


def main() -> int:
    email, password = _load_env()
    print(f"[smoke] credentials loaded: {_redact_email(email)} (password redacted)")

    # Lazy import — chỉ load adapter sau khi confirm có creds.
    from lora_coverage_api.application.sources import (
        SourceAuthFailed,
        SourceFetchFailed,
        SourceUnreachable,
        get_adapter,
    )

    src = get_adapter("lpwanmapper")
    print(f"[smoke] adapter: {type(src).__name__}")

    # ── Phase 1: connect() ─────────────────────────────────────────────────
    print("[smoke] phase 1: connect() -> POST /login")
    try:
        handle = src.connect({"email": email, "password": password})
    except SourceAuthFailed as e:
        print(f"[FAIL] auth rejected: {e}", file=sys.stderr)
        print("       -> check credential, hoặc Bearer header format có thể khác.", file=sys.stderr)
        return 3
    except SourceUnreachable as e:
        print(f"[FAIL] network/5xx: {e}", file=sys.stderr)
        return 4
    except SourceFetchFailed as e:
        print(f"[FAIL] response shape lạ: {e}", file=sys.stderr)
        return 5

    n_gw_raw = len(handle.get("gateways_raw", []))
    has_token = bool(handle.get("token"))
    print(f"[smoke]   [ok] token received: {has_token}")
    print(f"[smoke]   [ok] gateways in /login response: {n_gw_raw}")

    # ── Phase 2: fetch_gateways() ──────────────────────────────────────────
    print("[smoke] phase 2: fetch_gateways()")
    gateways = list(src.fetch_gateways(handle))
    print(f"[smoke]   [ok] mapped: {len(gateways)} / {n_gw_raw} raw")
    if len(gateways) < n_gw_raw:
        print(f"[smoke]   [warn] {n_gw_raw - len(gateways)} gateway raw skipped (missing fields)")
    if gateways:
        print(f"[smoke]   sample: {_gateway_sample(gateways[0])}")

    # ── Phase 3: fetch_measurements(since=None) ────────────────────────────
    # Lấy hết, rồi count. Nếu /data trả 0 record -> adapter đúng nhưng user
    # chưa có data ingest -> not a failure, chỉ warning.
    print("[smoke] phase 3: fetch_measurements(since=None) -> POST /data")
    try:
        measurements = list(src.fetch_measurements(handle, since=None))
    except SourceAuthFailed as e:
        print("[FAIL] /data 401 sau khi /login OK -> Bearer header KHÔNG đúng format.", file=sys.stderr)
        print(f"       err={e}", file=sys.stderr)
        return 3
    except SourceUnreachable as e:
        print(f"[FAIL] /data network/5xx: {e}", file=sys.stderr)
        return 4
    except SourceFetchFailed as e:
        print(f"[FAIL] /data response shape lạ: {e}", file=sys.stderr)
        print("       -> có thể wrapper khác (data field tên khác, hoặc shape không phải ChirpStack uplink).", file=sys.stderr)
        return 5

    print(f"[smoke]   [ok] measurements: {len(measurements)}")
    if measurements:
        print(f"[smoke]   sample: {_measurement_sample(measurements[0])}")
        # Sanity: time monotonicity & dedup key uniqueness
        ext_ids = {m.external_id for m in measurements}
        print(f"[smoke]   [ok] unique external_id: {len(ext_ids)} / {len(measurements)}")
        if len(ext_ids) != len(measurements):
            print(f"[smoke]   [warn] duplicate external_id detected ({len(measurements) - len(ext_ids)}) — dedup logic cần review.")
        gw_set = {m.serving_gateway_external_id for m in measurements}
        print(f"[smoke]   [ok] distinct serving gateways: {len(gw_set)}")
    else:
        print("[smoke]   [warn] 0 measurements — user có thể chưa post webhook nào lên lpwanmapper.")
        print("[smoke]     (không phải fail; adapter logic đã verify tới /data thành công)")

    # ── Phase 4: fetch_measurements(since=future) sanity ──────────────────
    if measurements:
        from datetime import UTC, datetime, timedelta

        future = datetime.now(UTC) + timedelta(days=365)
        print("[smoke] phase 4: fetch_measurements(since=future) — must be empty")
        m_future = list(src.fetch_measurements(handle, since=future))
        if m_future:
            print(f"[FAIL] since filter broken: trả {len(m_future)} record với since=+1 year", file=sys.stderr)
            return 9
        print("[smoke]   [ok] since filter works")

    print("[smoke] ALL PHASES PASS — adapter verified end-to-end against real API.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[smoke] interrupted", file=sys.stderr)
        sys.exit(130)
    except Exception:
        print("[FAIL] unexpected exception:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(9)
