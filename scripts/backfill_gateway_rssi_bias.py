"""Backfill geo.gateways.rssi_bias_db = hiệu chỉnh bias physics per-gateway.

Logic:
  Cho mỗi gateway có >= MIN_SAMPLES survey row, rssi_bias_db =
  mean(measured_rssi - physics_rssi) trên các row đó. Stage1ItuModel cộng giá
  trị này vào RSSI dự đoán (trừ khỏi pl_db) → sửa sai số hệ thống riêng từng
  gateway (chiều cao/vị trí anten/môi trường thực ≠ nominal).

  physics_rssi = device_eirp + gw_gain - PL(P.1812 + DSM). PHẢI dùng CÙNG cấu
  hình backend production (LORA_SURFACE_DEM_DIRECTORY) để bias khớp lúc áp.

  Đo trên spatial holdout: per-gw bias giảm test RMSE 13.88 -> 8.32 dB, bias ~0.

[!] PHỤ THUỘC CẤU HÌNH PHYSICS: bias = mean(đo - physics) nên gắn chặt với DSM +
  location% lúc fit. ĐỔI `LORA_SURFACE_DEM_DIRECTORY` hoặc `LORA_ITU_PERCENT_LOCATION`
  → PHẢI chạy lại script này (bias cũ sẽ sai). Config dùng được log lúc chạy.

Bias lớn là HỢP LỆ, không phải lỗi metadata (điều tra 2026-06-27): gateway trên
  núi (vd Sơn Trà 7276ff002e062cf2, +12 dB) hoặc đô thị có DSM phủ ô gateway
  (+20 dB) → physics over-attenuate, bias sửa đúng. Anten height nominal hợp lý.

Leak-free eval: mặc định fit trên TẤT CẢ survey (production muốn bias tốt nhất).
  Để eval holdout KHÔNG leak, BẮT BUỘC dùng --until trước cửa sổ holdout.

Chạy (repo root, .env có LORA_DEM_DIRECTORY + LORA_SURFACE_DEM_DIRECTORY):
    uv run python scripts/backfill_gateway_rssi_bias.py [--dry-run] [--min-samples 20]
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger("backfill_rssi_bias")

DEVICE_EIRP_DBM = 16.0  # AS923 cap 14 dBm + default TX gain 2 dBi (domain.coverage)
MAX_LINK_KM = 50.0
MIN_SAMPLES_DEFAULT = 20


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="In bias, KHÔNG ghi DB")
    parser.add_argument("--min-samples", type=int, default=MIN_SAMPLES_DEFAULT)
    parser.add_argument("--since", default=None, help="ISO date lọc survey từ (leak-free eval)")
    parser.add_argument("--until", default=None, help="ISO date lọc survey đến (leak-free eval)")
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    os.environ.setdefault("JWT_SECRET", "x" * 32)
    os.environ.setdefault("LINKING_FERNET_KEYS", "ZmFrZWtleWZha2VrZXlmYWtla2V5ZmFrZWtleWZha2VrZXk=")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services/api-service/src"))

    import psycopg
    from lora_coverage_api.application.itu.backend import GeoPoint, LinkGeometry
    from lora_coverage_api.config import get_settings
    from lora_coverage_api.infrastructure.itu.crc_covlib_backend import CrcCovlibBackend

    s = get_settings()
    surface = Path(s.lora_surface_dem_directory) if s.lora_surface_dem_directory else None
    backend = CrcCovlibBackend(
        dem_directory=Path(s.lora_dem_directory),
        surface_dem_directory=surface,
        percent_time=s.lora_itu_percent_time,
        percent_location=s.lora_itu_percent_location,
    )
    log.info(
        "Physics backend: DEM=%s surface=%s loc%%=%s",
        s.lora_dem_directory,
        surface,
        s.lora_itu_percent_location,
    )

    url = s.database_url.replace("postgresql+psycopg://", "postgresql://")
    clauses = [
        "t.rssi_dbm IS NOT NULL",
        "t.serving_gateway_id IS NOT NULL",
        "ST_DistanceSphere(t.location::geometry, gw.location::geometry) < %(maxd)s",
    ]
    params: dict[str, object] = {"maxd": MAX_LINK_KM * 1000.0}
    if args.since:
        clauses.append('t."timestamp" >= %(since)s')
        params["since"] = args.since
    if args.until:
        clauses.append('t."timestamp" < %(until)s')
        params["until"] = args.until
    sql = f"""
        SELECT gw.id::text AS gid, gw.code,
               ST_Y(t.location::geometry) AS lat, ST_X(t.location::geometry) AS lon,
               t.rssi_dbm,
               ST_Y(gw.location::geometry) AS glat, ST_X(gw.location::geometry) AS glon,
               gw.antenna_height_m, gw.antenna_gain_dbi, gw.frequency_mhz
        FROM ts.survey_training t JOIN geo.gateways gw ON gw.id = t.serving_gateway_id
        WHERE {" AND ".join(clauses)}
    """

    with psycopg.connect(url) as conn:
        rows = conn.execute(sql, params).fetchall()
        log.info("Loaded %d survey rows", len(rows))

        # gid -> [residual, ...]
        resid: dict[str, list[float]] = {}
        code_of: dict[str, str] = {}
        n = 0
        for gid, code, lat, lon, rssi, glat, glon, gh, ggain, gfreq in rows:
            link = LinkGeometry(
                tx=GeoPoint(float(glat), float(glon)),
                rx=GeoPoint(float(lat), float(lon)),
                tx_antenna_height_m=float(gh or 15.0),
                rx_antenna_height_m=1.5,
                freq_mhz=float(gfreq or 923.0),
            )
            try:
                pl = backend.basic_transmission_loss_db(link)
            except Exception:
                continue
            if not math.isfinite(pl):
                continue
            physics = DEVICE_EIRP_DBM + float(ggain or 0.0) - pl
            resid.setdefault(gid, []).append(float(rssi) - physics)
            code_of[gid] = code
            n += 1
            if n % 2000 == 0:
                log.info("  physics %d/%d", n, len(rows))

        updates: list[tuple[str, float, int]] = []
        for gid, rs in resid.items():
            if len(rs) < args.min_samples:
                log.info(
                    "  [%s] %d rows < min %d → skip (giữ NULL)",
                    code_of[gid],
                    len(rs),
                    args.min_samples,
                )
                continue
            bias = float(sum(rs) / len(rs))
            bias = max(-60.0, min(60.0, bias))  # clamp vào CHECK range
            updates.append((gid, round(bias, 2), len(rs)))

        updates.sort(key=lambda x: x[1])
        log.info("=== Per-gateway RSSI bias (mean measured-physics) ===")
        for gid, bias, cnt in updates:
            log.info("  %-18s bias=%+6.2f dB  (n=%d)", code_of[gid], bias, cnt)

        if args.dry_run:
            log.info("DRY-RUN: %d gateway sẽ được set rssi_bias_db (không ghi).", len(updates))
            return 0

        for gid, bias, _ in updates:
            conn.execute("UPDATE geo.gateways SET rssi_bias_db = %s WHERE id = %s", (bias, gid))
        conn.commit()
        log.info("Đã ghi rssi_bias_db cho %d gateway.", len(updates))
    return 0


if __name__ == "__main__":
    sys.exit(main())
