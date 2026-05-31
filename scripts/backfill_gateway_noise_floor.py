"""Backfill geo.gateways.noise_floor_dbm từ historical survey data.

Logic:
  Cho mỗi gateway có >= MIN_SAMPLES survey row trong train window (Nov-Dec 2025),
  noise_floor_dbm = median(rssi_dbm - snr_db) trên các row đó.

  Lý do dùng median:
    - Robust với outlier (1 row interference bất thường).
    - Khớp với analysis trong test_noise_floor_options_2026_05_31.py (Option B
      đạt RMSE 11.11 dB vs current 23.80 dB).

  Lý do giới hạn train window Nov-Dec 2025:
    - Tránh leak vào Jan-Feb 2026 holdout — NF derived từ holdout sẽ làm
      Stage 1 metric trên holdout không còn unbiased.

Gateway nào không đủ MIN_SAMPLES sẽ giữ NULL → app layer fallback
DEFAULT_NOISE_FLOOR_DBM (-104).

Chạy:
    LORA_DB_URL=postgresql://... uv run python scripts/backfill_gateway_noise_floor.py [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

log = logging.getLogger(__name__)

MIN_SAMPLES = 20  # ngưỡng để NF có ý nghĩa thống kê
TRAIN_START = "2025-11-01"
TRAIN_END = "2025-12-31"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ in NF tính được, không UPDATE DB.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )

    import psycopg

    db_url = os.environ["LORA_DB_URL"]

    sql_compute = """
        SELECT gw.id::text AS id,
               gw.code,
               COUNT(*) AS n,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY t.rssi_dbm - t.snr_db) AS nf_median
        FROM ts.survey_training t
        JOIN geo.gateways gw ON gw.id = t.serving_gateway_id
        WHERE t.timestamp >= %s::date AND t.timestamp <= %s::date
          AND t.rssi_dbm IS NOT NULL
          AND t.snr_db IS NOT NULL
          AND t.serving_gateway_id IS NOT NULL
        GROUP BY gw.id, gw.code
        HAVING COUNT(*) >= %s
        ORDER BY gw.code
    """

    sql_update = "UPDATE geo.gateways SET noise_floor_dbm = %s WHERE id = %s"

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql_compute, (TRAIN_START, TRAIN_END, MIN_SAMPLES))
        rows = cur.fetchall()
        log.info(
            "Tính NF cho %d gateway có n>=%d trong [%s, %s]",
            len(rows),
            MIN_SAMPLES,
            TRAIN_START,
            TRAIN_END,
        )

        for gw_id, code, n, nf in rows:
            nf_f = float(nf)
            log.info("  %s  n=%4d  NF=%.2f dBm", code, n, nf_f)
            if not -130.0 <= nf_f <= -80.0:
                log.warning("    NF ngoài range [-130, -80], bỏ qua %s", code)
                continue
            if not args.dry_run:
                cur.execute(sql_update, (nf_f, gw_id))

        if not args.dry_run:
            conn.commit()
            log.info("Đã commit UPDATE cho %d gateway.", len(rows))
        else:
            log.info("DRY-RUN — không UPDATE DB.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
