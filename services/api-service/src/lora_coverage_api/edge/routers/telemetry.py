"""telemetry — endpoint public dem pageview cho admin dashboard.

Frontend (App.jsx) goi POST /telemetry/visit moi khi component mount → +1
cho ngay hien tai trong audit.daily_visits. Khong yeu cau auth, khong dedupe
theo user / IP — counter raw cho admin "Tong quan".

Khong them rate-limit phia server: nguy co spam admin chart la viec ai do
auto-bot site, khong dang lo trong scope DATN nay.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from ..deps import _engine

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


_UPSERT_VISIT = text("""
    INSERT INTO audit.daily_visits (day, count)
    VALUES (CURRENT_DATE, 1)
    ON CONFLICT (day) DO UPDATE SET count = audit.daily_visits.count + 1
""")


@router.post("/visit", status_code=status.HTTP_204_NO_CONTENT)
def record_visit() -> Response:
    """Fire-and-forget: +1 cho ngay hien tai. Khong tra body."""
    with _engine().begin() as conn:
        conn.execute(_UPSERT_VISIT)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
