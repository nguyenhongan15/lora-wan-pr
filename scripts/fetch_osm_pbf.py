"""Tải OSM PBF mới nhất cho Việt Nam từ Geofabrik (nguồn chính xác nhất — chính
là dữ liệu OSM gốc, cập nhật hằng ngày, có tag loại nhà để suy chiều cao DSM).

Dùng bởi Celery task `refresh_geo_data` (làm tươi footprint nhà hàng tháng) hoặc
chạy tay. Stream download → verify MD5 (sidecar .md5 của Geofabrik) → atomic
rename, để PBF đang dùng không bao giờ bị thay bằng file tải dở.

Usage:
    python scripts/fetch_osm_pbf.py                       # → $LORA_OSM_PBF_PATH hoặc default
    python scripts/fetch_osm_pbf.py --out /geo/osm/vietnam-latest.osm.pbf
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("fetch_osm_pbf")

# Geofabrik Vietnam extract — daily-refreshed, authoritative OSM mirror.
DEFAULT_URL = "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf"
# PBF VN ~300-400MB; nhỏ hơn nhiều = tải lỗi / redirect HTML.
_MIN_VALID_BYTES = 50 * 1024 * 1024
_CHUNK = 1024 * 1024


def _stream_download(url: str, dst_tmp: Path) -> str:
    """Tải `url` → `dst_tmp`, trả md5 hex tính trong lúc stream."""
    md5 = hashlib.md5()
    total = 0
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "lora-coverage-geo-refresh/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, dst_tmp.open("wb") as fh:
        while True:
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            fh.write(chunk)
            md5.update(chunk)
            total += len(chunk)
            if total % (50 * _CHUNK) < _CHUNK:
                log.info(
                    "  ... %.0f MB (%.0f MB/s)",
                    total / 1e6,
                    total / 1e6 / max(time.time() - t0, 1e-3),
                )
    log.info("Downloaded %.0f MB in %.0fs", total / 1e6, time.time() - t0)
    if total < _MIN_VALID_BYTES:
        raise RuntimeError(
            f"PBF chỉ {total} bytes (< {_MIN_VALID_BYTES}) — có thể tải lỗi/redirect"
        )
    return md5.hexdigest()


def _fetch_expected_md5(url: str) -> str | None:
    """Đọc sidecar `<url>.md5` của Geofabrik (format: '<hex>  <filename>'). None nếu không có."""
    try:
        req = urllib.request.Request(url + ".md5", headers={"User-Agent": "lora-coverage/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode().strip().split()[0].lower()
    except Exception as exc:
        log.warning("Không lấy được .md5 sidecar (%s) — bỏ qua verify", exc)
        return None


def fetch(url: str, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    log.info("Fetching %s → %s", url, out)
    got_md5 = _stream_download(url, tmp)
    expected = _fetch_expected_md5(url)
    if expected and got_md5 != expected:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"MD5 mismatch: got {got_md5}, expected {expected}")
    if expected:
        log.info("MD5 verified: %s", got_md5)
    tmp.replace(out)  # atomic trên cùng filesystem
    log.info("Saved %s (%.0f MB)", out, out.stat().st_size / 1e6)
    return out


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="OSM PBF URL (default Geofabrik VN)")
    parser.add_argument(
        "--out",
        default=os.environ.get("LORA_OSM_PBF_PATH", "/geo/osm/vietnam-latest.osm.pbf"),
        help="Đường dẫn output (default $LORA_OSM_PBF_PATH hoặc /geo/osm/vietnam-latest.osm.pbf)",
    )
    args = parser.parse_args()
    try:
        fetch(args.url, Path(args.out))
    except Exception as exc:
        log.error("Tải OSM PBF thất bại: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
