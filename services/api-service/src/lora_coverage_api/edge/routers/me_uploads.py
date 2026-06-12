"""CSV/JSON survey upload — luôn upload "private" trước, "Đóng góp" sau.

Plan community-data-contribution §4 + refactor 2026-06-11 (batch-based).
User upload file mỗi dòng/object = 1 reading. Endpoint:
  1. Parse ở backend (KHÔNG trust FE đã validate).
  2. Tạo 1 row `me.upload_batches` (kind ∈ {csv,json}).
  3. Ghi quarantine với batch_id + submitted_for_community=false.
  4. Trả `inserted_count` + batch_id.

Đóng góp = action riêng (POST /api/v1/me/uploads/batches/{id}/submit, mig
0024 + Task #4) — user tự bấm "Đóng góp" trên 1 batch trong "Quản lý dữ
liệu" sau khi upload xong, không còn checkbox lúc upload.

Hai định dạng được hỗ trợ:
  * CSV — header chuẩn (timestamp, latitude, longitude, rssi_dbm, snr_db,
    spreading_factor, gateway_code; tuỳ chọn frequency_mhz, device_id).
  * JSON — auto-detect 2 dạng:
      - Format A: array các object cùng schema với CSV (1 object = 1 row).
      - Format C: webhook payload từ TTN v3 (`uplink_message`) hoặc
        ChirpStack v4 (`rxInfo`). 1 event → N rows tương ứng N gateway thấy
        uplink trong `rx_metadata`/`rxInfo`.

Idempotency: external_id = sha256(user_id + ts_iso + lat + lng + gateway_code
+ sf)[:32]. Cùng row CSV reupload → cùng external_id → UNIQUE PARTIAL
`(timestamp, source_type, external_id)` chặn duplicate insert. User có thể
reupload an toàn (vd sửa typo 1 dòng rồi re-submit) — tạo batch mới nhưng
0 row insert.

Rate limit: per IP qua `me_csv_upload_rate_limit` (10/hour default). Per-user
quota chính xác hơn nhưng slowapi không native; IP đủ cho v1.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from ...application.identity import EmailNotVerifiedError, User
from ...application.repositories import GatewayDirectory, SurveyIngest
from ...application.uploads import (
    UploadKind,
    create_upload_batch,
    delete_batch,
    fetch_upload_overview,
    list_upload_batches,
    set_batch_points_count,
    submit_batch_for_review,
)
from ...config import get_settings
from ...domain.coverage import Gateway, GatewayId
from ...domain.survey import SurveyBatch, SurveyRecord, UploaderId
from ..deps import (
    _engine,
    current_user,
    gateway_directory,
    survey_repository,
)
from ..rate_limit import limiter
from ..schemas import (
    CsvUploadResponse,
    UploadBatchDeleteResponse,
    UploadBatchItem,
    UploadBatchListResponse,
    UploadBatchSubmitResponse,
    UploadOverviewResponse,
)

router = APIRouter(prefix="/api/v1/me/uploads", tags=["me-uploads"])

logger = structlog.get_logger("lora_coverage_api.me_uploads")

# Settings resolve 1 lần — decorator @limiter.limit cần string lúc import.
_settings = get_settings()

# Cap rows/file để 1 user không thể fan-out 100k row ITU compute (mỗi row
# pipeline tốn ~10ms cho Stage1 prediction). 1000 = đủ cho 1 đợt survey
# realistic (vài chục km drive test).
_MAX_ROWS = 1000

# File size cap defensive — 1MB đủ cho 1000 row CSV thông thường (~700 bytes/row).
_MAX_FILE_BYTES = 1_048_576

# Required = không default được. SNR đã rời khỏi đây — vẫn parse nhưng default
# 0.0 nếu thiếu (xem `_build_record`). SF/RSSI/vị trí/timestamp/gateway là input
# vật lý cốt lõi của LoRa propagation; không có cách nào impute từ data khác →
# thiếu thì reject row (kèm reason để user sửa).
_REQUIRED_FIELDS = (
    "timestamp",
    "latitude",
    "longitude",
    "rssi_dbm",
    "spreading_factor",
    "gateway_code",
)

# Header alias — chuẩn hoá tên cột về canonical (lower-case, strip). User upload
# từ TTN/ChirpStack/Helium/CSV tự chế đều có convention khác nhau; thay vì bắt
# user đổi tên cột, mình map. Lookup case-insensitive sau strip.
#
# Lưu ý: KHÔNG include tên tiếng Việt — nếu user export từ tool VN tự chế, họ
# sẽ thấy reason rõ và sửa file dễ hơn là mình đoán bừa.
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "time", "ts", "datetime", "date_time", "received_at", "rx_time"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lng", "lon", "long"),
    "rssi_dbm": ("rssi_dbm", "rssi", "rssi_db"),
    "snr_db": ("snr_db", "snr", "snr_db_value"),
    "spreading_factor": (
        "spreading_factor",
        "sf",
        "spreadingfactor",
        "spreading-factor",
    ),
    "gateway_code": (
        "gateway_code",
        "gateway_id",
        "gateway",
        "gw_id",
        "gw",
        "gwid",
        "gateway_name",
        "gatewayid",
    ),
    "frequency_mhz": ("frequency_mhz", "frequency", "freq", "freq_mhz"),
    "device_id": (
        "device_id",
        "device",
        "deveui",
        "dev_eui",
        "device_name",
        "devicename",
    ),
}

# Build reverse lookup: alias_lower → canonical_field. Module-level cache.
_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias.lower(): canonical for canonical, aliases in _HEADER_ALIASES.items() for alias in aliases
}

_SOURCE_TYPE = "csv_upload"


@router.post(
    "/csv",
    response_model=CsvUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload CSV/JSON survey — tạo 1 batch private (chưa đóng góp)",
    responses={
        400: {"description": "File rỗng / sai schema header / quá lớn"},
        401: {"description": "Chưa đăng nhập"},
        429: {"description": "Rate limit exceeded"},
    },
)
@limiter.limit(_settings.me_csv_upload_rate_limit)
async def upload_survey_csv(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    repo: Annotated[SurveyIngest, Depends(survey_repository)],
    directory: Annotated[GatewayDirectory, Depends(gateway_directory)],
    file: Annotated[UploadFile, File(description="CSV hoặc JSON (UTF-8)")],
) -> CsvUploadResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="File rỗng")
    if len(raw) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File quá lớn ({len(raw)} bytes); giới hạn {_MAX_FILE_BYTES} bytes",
        )

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File không phải UTF-8") from None

    filename_lower = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    is_json = filename_lower.endswith(".json") or content_type.startswith("application/json")
    kind: UploadKind = "json" if is_json else "csv"
    # Filename hiển thị nguyên (không lowercase) — UI mục Lịch sử upload show
    # cho user. Fallback khi UploadFile.filename None (rare nhưng spec cho phép).
    display_filename = file.filename or ("upload.json" if is_json else "upload.csv")

    if is_json:
        parsed, parse_rejected_reasons = _parse_json(text, user_id=user.id, directory=directory)
    else:
        parsed, parse_rejected_reasons = _parse_csv(
            io.StringIO(text), user_id=user.id, directory=directory
        )
    parsed_count = len(parsed)
    parse_rejected_count = len(parse_rejected_reasons)

    if parsed_count == 0:
        # Không tạo batch row khi 0 row parse — để UI Lịch sử upload không
        # chứa "rác" file không hợp lệ; user thấy lỗi ngay trong response.
        return CsvUploadResponse(
            batch_id=None,
            parsed_count=0,
            parse_rejected_count=parse_rejected_count,
            parse_rejected_reasons=parse_rejected_reasons[:50],
            inserted_count=0,
        )

    records = [p.record for p in parsed]
    external_ids: list[str | None] = [p.external_id for p in parsed]
    record_ids = [uuid4() for _ in parsed]
    batch = SurveyBatch(uploader_id=UploaderId(user.id), records=records)

    # Split 3 transaction vì `SurveyIngest.write_quarantine_idempotent` mở
    # `self._engine.begin()` riêng → không thấy batch row nếu vẫn còn ở
    # outer tx → FK violation (ts.survey_quarantine.batch_id REFERENCES
    # me.upload_batches.id). Trình tự:
    #   1. commit batch row (uploaded_at = now() default từ DB).
    #   2. repo write quarantine (FK thoả vì batch đã commit).
    #   3. commit points_count cache.
    # Risk: step 2 fail → orphan batch row với points_count=0. User thấy
    # trong "Lịch sử upload" và tự xoá được — chấp nhận.
    with _engine().begin() as conn:
        batch_id, _ = create_upload_batch(
            conn,
            user_id=user.id,
            kind=kind,
            filename=display_filename,
            linked_source_id=None,
            points_count=0,
        )
    inserted_count = repo.write_quarantine_idempotent(
        batch,
        record_ids,
        external_ids=external_ids,
        source_type=_SOURCE_TYPE,
        linked_source_id=None,
        contributor_user_id=user.id,
        submitted_for_community=False,
        batch_id=batch_id,
    )
    with _engine().begin() as conn:
        set_batch_points_count(conn, batch_id=batch_id, count=inserted_count)

    logger.info(
        "csv_upload_ingested",
        user_id=str(user.id),
        batch_id=str(batch_id),
        kind=kind,
        parsed=parsed_count,
        parse_rejected=parse_rejected_count,
        inserted=inserted_count,
        trace_id=getattr(request.state, "trace_id", None),
    )

    return CsvUploadResponse(
        batch_id=batch_id,
        parsed_count=parsed_count,
        parse_rejected_count=parse_rejected_count,
        parse_rejected_reasons=parse_rejected_reasons[:50],
        inserted_count=inserted_count,
    )


@router.get(
    "/overview",
    response_model=UploadOverviewResponse,
    summary="Tổng quan dữ liệu của user (batches + points theo trạng thái)",
)
async def upload_overview(
    user: Annotated[User, Depends(current_user)],
) -> UploadOverviewResponse:
    with _engine().begin() as conn:
        overview = fetch_upload_overview(conn, user.id)
    return UploadOverviewResponse(
        batches_total=overview.batches_total,
        points_total=overview.points_total,
        public_batches=overview.public_batches,
        pending_batches=overview.pending_batches,
        private_batches=overview.private_batches,
    )


@router.get(
    "/batches",
    response_model=UploadBatchListResponse,
    summary="Danh sách batch upload của user — Quản lý dữ liệu / Lịch sử upload",
)
async def list_batches(
    user: Annotated[User, Depends(current_user)],
    include_deleted: bool = True,
) -> UploadBatchListResponse:
    """`include_deleted=true` (default) → Lịch sử upload (đầy đủ). `false`
    → Quản lý dữ liệu (chỉ batch còn sống). Trạng thái suy ở backend."""
    with _engine().begin() as conn:
        batches = list_upload_batches(conn, user_id=user.id, include_deleted=include_deleted)
    return UploadBatchListResponse(
        items=[
            UploadBatchItem(
                id=b.id,
                kind=b.kind,
                filename=b.filename,
                linked_source_id=b.linked_source_id,
                uploaded_at=b.uploaded_at,
                points_count=b.points_count,
                status=b.status,
                deleted_at=b.deleted_at,
            )
            for b in batches
        ]
    )


@router.post(
    "/batches/{batch_id}/submit",
    response_model=UploadBatchSubmitResponse,
    status_code=status.HTTP_200_OK,
    summary="Đóng góp 1 batch cho cộng đồng — gửi admin duyệt",
    responses={
        401: {"description": "Chưa đăng nhập"},
        403: {"description": "Chưa xác thực email"},
        429: {"description": "Rate limit exceeded"},
    },
)
@limiter.limit(_settings.me_csv_upload_rate_limit)
async def submit_batch(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    batch_id: UUID,
) -> UploadBatchSubmitResponse:
    """Mark rows của batch submitted_for_community=true + chuyển sang
    pending_review. Idempotent: re-call → 0. KHÔNG raise 404 khi batch
    không thuộc user — filter `uploader_id` trong SQL trả 0 rows."""
    if not user.email_verified:
        raise EmailNotVerifiedError("Cần xác thực email trước khi đóng góp dữ liệu cho cộng đồng")

    with _engine().begin() as conn:
        queued = submit_batch_for_review(conn, user_id=user.id, batch_id=batch_id)

    logger.info(
        "upload_batch_submit_invoked",
        user_id=str(user.id),
        batch_id=str(batch_id),
        queued=queued,
        trace_id=getattr(request.state, "trace_id", None),
    )
    return UploadBatchSubmitResponse(batch_id=batch_id, queued=queued)


@router.delete(
    "/batches/{batch_id}",
    response_model=UploadBatchDeleteResponse,
    summary="Xoá 1 batch — soft-delete + hard-purge rows con (cả training)",
    responses={
        401: {"description": "Chưa đăng nhập"},
        404: {"description": "Batch không tồn tại / không thuộc user / đã xoá"},
    },
)
async def delete_upload_batch(
    user: Annotated[User, Depends(current_user)],
    batch_id: UUID,
) -> UploadBatchDeleteResponse:
    with _engine().begin() as conn:
        ok = delete_batch(conn, user_id=user.id, batch_id=batch_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Batch không tồn tại")
    logger.info(
        "upload_batch_delete_invoked",
        user_id=str(user.id),
        batch_id=str(batch_id),
    )
    return UploadBatchDeleteResponse(batch_id=batch_id, deleted=True)


# ── parsing helpers ───────────────────────────────────────────────────────


class _ParsedRow:
    __slots__ = ("external_id", "record")

    def __init__(self, record: SurveyRecord, external_id: str) -> None:
        self.record = record
        self.external_id = external_id


def _normalize_header(raw_header: str) -> str | None:
    """Map 1 tên cột bất kỳ → canonical field name. None = không nhận diện."""
    return _ALIAS_TO_CANONICAL.get(raw_header.strip().lower())


def _canonicalize_row(raw_row: dict[str, str], header_map: dict[str, str | None]) -> dict[str, str]:
    """Translate dict keys raw → canonical. Drop key không có canonical mapping
    (cột thừa user upload — vd 'note', 'tags' — vẫn được phép tồn tại trong file
    nhưng không lưu, vì DB không có column tương ứng).
    """
    out: dict[str, str] = {}
    for original_key, value in raw_row.items():
        canonical = header_map.get(original_key)
        if canonical is not None:
            out[canonical] = value
    return out


def _parse_csv(
    text_io: io.StringIO,
    *,
    user_id: UUID,
    directory: GatewayDirectory,
) -> tuple[list[_ParsedRow], list[str]]:
    """Parse CSV → (parsed rows, rejected reasons với line number).

    KHÔNG raise — bad rows skip cùng reason text; caller bao gồm reasons trong
    response để FE hiển thị "dòng N: lý do" cho user sửa.

    Header normalize qua `_HEADER_ALIASES` → thứ tự cột không quan trọng, tên
    cột case-insensitive + nhiều synonym chấp nhận, cột thừa bị drop. Chỉ
    reject file-level khi thiếu canonical fields trong `_REQUIRED_FIELDS`.
    """
    reader = csv.DictReader(text_io)
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="File không có header")

    header_map: dict[str, str | None] = {h: _normalize_header(h) for h in reader.fieldnames}
    canonical_present = {v for v in header_map.values() if v is not None}
    missing = [f for f in _REQUIRED_FIELDS if f not in canonical_present]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(f"Thiếu cột bắt buộc (đã thử các tên tương đương): {', '.join(missing)}"),
        )

    # Cache gateway_code → Gateway (1 CSV thường dùng vài gateway). Miss → None
    # vẫn cache để không truy vấn lặp.
    gw_cache: dict[str, Gateway | None] = {}

    parsed: list[_ParsedRow] = []
    rejected: list[str] = []

    for i, row in enumerate(reader, start=2):  # start=2: line 1 = header
        if len(parsed) >= _MAX_ROWS:
            rejected.append(f"dòng {i}: vượt giới hạn {_MAX_ROWS} dòng/file")
            break

        canonical_row = _canonicalize_row(row, header_map)
        try:
            record, external_id = _build_record(
                canonical_row,
                user_id=user_id,
                directory_cache=gw_cache,
                directory=directory,
            )
        except _RowError as exc:
            rejected.append(f"dòng {i}: {exc}")
            continue
        parsed.append(_ParsedRow(record, external_id))

    return parsed, rejected


class _RowError(Exception):
    """Lỗi 1 row CSV — message tiếng Việt để hiển thị trực tiếp."""


def _build_record(
    row: dict[str, str],
    *,
    user_id: UUID,
    directory_cache: dict[str, Gateway | None],
    directory: GatewayDirectory,
) -> tuple[SurveyRecord, str]:
    """Validate + parse 1 row CSV thành SurveyRecord + external_id.

    Raises _RowError với message tiếng Việt nếu schema/range fail.
    """
    ts_raw = (row.get("timestamp") or "").strip()
    if not ts_raw:
        raise _RowError("timestamp rỗng")
    try:
        # Accept ISO 8601 (with/without timezone). Empty timezone → giả định UTC
        # để PostgreSQL TIMESTAMPTZ insert đúng (mọi store ở UTC).
        ts = datetime.fromisoformat(ts_raw)
    except ValueError as exc:
        raise _RowError(f"timestamp không phải ISO 8601: {ts_raw}") from exc
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)

    lat = _parse_float(row.get("latitude"), "latitude")
    lon = _parse_float(row.get("longitude"), "longitude")
    rssi = _parse_float(row.get("rssi_dbm"), "rssi_dbm")
    # SNR thiếu → default 0 dB. DB column NOT NULL nên không thể NULL; 0 là
    # "unknown / không xác định" — Stage 1 bottleneck label sẽ tính SF12 SNR
    # limit = -20 dB, 0 dB không trigger SNR bottleneck → an toàn cho training
    # filter (chỉ ảnh hưởng analysis chi tiết, không bias coverage estimate).
    snr = _parse_float(row.get("snr_db"), "snr_db", default=0.0)
    sf = _parse_int(row.get("spreading_factor"), "spreading_factor")
    freq = _parse_float(row.get("frequency_mhz"), "frequency_mhz", default=923.0)
    device_id_raw = (row.get("device_id") or "").strip()
    device_id = device_id_raw or None

    gateway_code = (row.get("gateway_code") or "").strip()
    if not gateway_code:
        raise _RowError("gateway_code rỗng")
    if gateway_code in directory_cache:
        gateway = directory_cache[gateway_code]
    else:
        gateway = directory.get_by_code(gateway_code)
        directory_cache[gateway_code] = gateway
    if gateway is None:
        raise _RowError(f"gateway_code '{gateway_code}' không tồn tại")

    try:
        record = SurveyRecord(
            timestamp=ts,
            latitude=lat,
            longitude=lon,
            rssi_dbm=rssi,
            snr_db=snr,
            spreading_factor=sf,
            frequency_mhz=freq,
            device_id=device_id,
            serving_gateway_id=GatewayId(gateway.id),
        )
    except ValueError as exc:
        # SurveyRecord.__post_init__ raise nếu range fail (rssi/snr/sf/lat/lng).
        raise _RowError(str(exc)) from exc

    external_id = _deterministic_external_id(
        user_id=user_id,
        ts_iso=ts.isoformat(),
        latitude=lat,
        longitude=lon,
        gateway_code=gateway_code,
        spreading_factor=sf,
    )
    return record, external_id


def _parse_float(raw: str | None, field: str, *, default: float | None = None) -> float:
    raw_s = (raw or "").strip()
    if not raw_s:
        if default is not None:
            return default
        raise _RowError(f"{field} rỗng")
    try:
        return float(raw_s)
    except ValueError as exc:
        raise _RowError(f"{field} không phải số: {raw_s}") from exc


def _parse_int(raw: str | None, field: str) -> int:
    raw_s = (raw or "").strip()
    if not raw_s:
        raise _RowError(f"{field} rỗng")
    try:
        return int(raw_s)
    except ValueError as exc:
        raise _RowError(f"{field} không phải số nguyên: {raw_s}") from exc


def _parse_json(
    raw_text: str,
    *,
    user_id: UUID,
    directory: GatewayDirectory,
) -> tuple[list[_ParsedRow], list[str]]:
    """Parse JSON body → (parsed rows, rejected reasons).

    Auto-detect:
      * Array với element đầu có key 'timestamp' → Format A (flat CSV-shape).
      * Array/dict không có 'timestamp' → Format C (webhook payload).
    """
    try:
        body = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"JSON không hợp lệ: {exc.msg} (vị trí {exc.pos})"
        ) from exc

    if isinstance(body, list):
        if not body:
            return [], []
        first = body[0]
        if isinstance(first, dict) and "timestamp" in first:
            return _parse_json_format_a(body, user_id=user_id, directory=directory)
        return _parse_json_format_c(body, user_id=user_id, directory=directory)
    if isinstance(body, dict):
        if "timestamp" in body and "latitude" in body:
            return _parse_json_format_a([body], user_id=user_id, directory=directory)
        return _parse_json_format_c([body], user_id=user_id, directory=directory)
    raise HTTPException(
        status_code=400,
        detail="JSON gốc phải là object (1 event) hoặc array (nhiều row/event)",
    )


def _parse_json_format_a(
    items: list[Any],
    *,
    user_id: UUID,
    directory: GatewayDirectory,
) -> tuple[list[_ParsedRow], list[str]]:
    gw_cache: dict[str, Gateway | None] = {}
    parsed: list[_ParsedRow] = []
    rejected: list[str] = []
    for i, item in enumerate(items, start=1):
        if len(parsed) >= _MAX_ROWS:
            rejected.append(f"item {i}: vượt giới hạn {_MAX_ROWS} item/file")
            break
        if not isinstance(item, dict):
            rejected.append(f"item {i}: không phải object JSON")
            continue
        # Normalize key qua alias (case-insensitive) như CSV — JSON user-defined
        # cũng dùng convention khác nhau (RSSI/rssi/rssi_dbm).
        raw_row = _stringify_row(item)
        header_map = {k: _normalize_header(k) for k in raw_row}
        canonical_row = _canonicalize_row(raw_row, header_map)
        try:
            record, external_id = _build_record(
                canonical_row,
                user_id=user_id,
                directory_cache=gw_cache,
                directory=directory,
            )
        except _RowError as exc:
            rejected.append(f"item {i}: {exc}")
            continue
        parsed.append(_ParsedRow(record, external_id))
    return parsed, rejected


def _parse_json_format_c(
    events: list[Any],
    *,
    user_id: UUID,
    directory: GatewayDirectory,
) -> tuple[list[_ParsedRow], list[str]]:
    gw_cache: dict[str, Gateway | None] = {}
    parsed: list[_ParsedRow] = []
    rejected: list[str] = []
    for i, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            rejected.append(f"event {i}: không phải object JSON")
            continue
        if "uplink_message" in event:
            extracted = _extract_from_ttn(event)
        elif "rxInfo" in event:
            extracted = _extract_from_chirpstack(event)
        else:
            rejected.append(
                f"event {i}: không nhận dạng được webhook "
                "(cần 'uplink_message' cho TTN hoặc 'rxInfo' cho ChirpStack)"
            )
            continue
        for j, candidate in enumerate(extracted, start=1):
            if isinstance(candidate, str):
                rejected.append(f"event {i} gw {j}: {candidate}")
                continue
            if len(parsed) >= _MAX_ROWS:
                rejected.append(f"event {i} gw {j}: vượt giới hạn {_MAX_ROWS} row/file")
                return parsed, rejected
            try:
                row = _stringify_row(candidate)
                record, external_id = _build_record(
                    row, user_id=user_id, directory_cache=gw_cache, directory=directory
                )
            except _RowError as exc:
                rejected.append(f"event {i} gw {j}: {exc}")
                continue
            parsed.append(_ParsedRow(record, external_id))
    return parsed, rejected


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce một JSON field về dict; nếu sai type/None thì trả {} để chain .get() an toàn."""
    return value if isinstance(value, dict) else {}


def _extract_from_ttn(event: dict[str, Any]) -> list[dict[str, Any] | str]:
    """TTN v3 uplink event → row dicts (1 per gateway in rx_metadata).

    Returns list of dict (good) hoặc str (error message cho 1 gw cụ thể).
    Trả về 1 element str duy nhất nếu event-level bị lỗi (vd thiếu locations).
    """
    msg = event.get("uplink_message")
    if not isinstance(msg, dict):
        return ["thiếu hoặc sai 'uplink_message'"]

    received_at = event.get("received_at") or msg.get("received_at")
    if not received_at:
        return ["thiếu 'received_at'"]

    settings = _as_dict(msg.get("settings"))
    dr = _as_dict(settings.get("data_rate"))
    lora_dr = _as_dict(dr.get("lora"))
    sf = lora_dr.get("spreading_factor")

    freq_raw = settings.get("frequency")
    freq_mhz: float | None
    try:
        freq_mhz = float(freq_raw) / 1_000_000 if freq_raw else None
    except (TypeError, ValueError):
        freq_mhz = None

    loc = _pick_ttn_location(msg.get("locations"))
    if loc is None:
        return ["thiếu uplink_message.locations.<source>.{latitude,longitude}"]

    end_device = _as_dict(event.get("end_device_ids"))
    device_id = end_device.get("device_id") or end_device.get("dev_eui")

    rx_list = msg.get("rx_metadata")
    if not isinstance(rx_list, list) or not rx_list:
        return ["thiếu uplink_message.rx_metadata"]

    rows: list[dict[str, Any] | str] = []
    for rx in rx_list:
        if not isinstance(rx, dict):
            rows.append("rx_metadata item không phải object")
            continue
        gw_ids = _as_dict(rx.get("gateway_ids"))
        gw_code = gw_ids.get("gateway_id") or gw_ids.get("eui")
        rows.append(
            {
                "timestamp": received_at,
                "latitude": loc.get("latitude"),
                "longitude": loc.get("longitude"),
                "rssi_dbm": rx.get("rssi"),
                "snr_db": rx.get("snr"),
                "spreading_factor": sf,
                "frequency_mhz": freq_mhz,
                "gateway_code": gw_code,
                "device_id": device_id,
            }
        )
    return rows


def _pick_ttn_location(locations: Any) -> dict[str, Any] | None:
    """TTN v3 locations object thường có 1 trong các source: user, device, gateway.

    Ưu tiên 'user' (ground-truth user-reported) > 'device' (GPS device) >
    'gateway' (= vị trí gateway, KHÔNG phải vị trí phép đo — fallback cuối).
    """
    if not isinstance(locations, dict) or not locations:
        return None
    for key in ("user", "device"):
        candidate = locations.get(key)
        if isinstance(candidate, dict) and candidate.get("latitude") is not None:
            return candidate
    for value in locations.values():
        if isinstance(value, dict) and value.get("latitude") is not None:
            return value
    return None


def _extract_from_chirpstack(event: dict[str, Any]) -> list[dict[str, Any] | str]:
    """ChirpStack v4 uplink event → row dicts (1 per rxInfo entry)."""
    received_at = event.get("time")
    if not received_at:
        return ["thiếu 'time'"]

    tx = _as_dict(event.get("txInfo"))
    modulation = _as_dict(tx.get("modulation"))
    lora_mod = _as_dict(modulation.get("lora"))
    sf = lora_mod.get("spreadingFactor")

    freq_raw = tx.get("frequency")
    freq_mhz: float | None
    try:
        freq_mhz = float(freq_raw) / 1_000_000 if freq_raw else None
    except (TypeError, ValueError):
        freq_mhz = None

    obj = _as_dict(event.get("object"))
    lat = obj.get("latitude")
    lng = obj.get("longitude")
    if lat is None or lng is None:
        return ["thiếu object.latitude/longitude (device payload phải decode lat/lng)"]

    device_info = _as_dict(event.get("deviceInfo"))
    device_id = device_info.get("devEui") or device_info.get("deviceName")

    rx_list = event.get("rxInfo")
    if not isinstance(rx_list, list) or not rx_list:
        return ["thiếu 'rxInfo'"]

    rows: list[dict[str, Any] | str] = []
    for rx in rx_list:
        if not isinstance(rx, dict):
            rows.append("rxInfo item không phải object")
            continue
        gw_code = rx.get("gatewayId") or rx.get("gatewayID")
        rows.append(
            {
                "timestamp": received_at,
                "latitude": lat,
                "longitude": lng,
                "rssi_dbm": rx.get("rssi"),
                "snr_db": rx.get("snr"),
                "spreading_factor": sf,
                "frequency_mhz": freq_mhz,
                "gateway_code": gw_code,
                "device_id": device_id,
            }
        )
    return rows


def _stringify_row(item: dict[str, Any]) -> dict[str, str]:
    """Coerce JSON value types → str để reuse _build_record (vốn parse từ CSV)."""
    out: dict[str, str] = {}
    for k, v in item.items():
        if v is None:
            out[k] = ""
        elif isinstance(v, bool):
            out[k] = "1" if v else "0"
        else:
            out[k] = str(v)
    return out


def _deterministic_external_id(
    *,
    user_id: UUID,
    ts_iso: str,
    latitude: float,
    longitude: float,
    gateway_code: str,
    spreading_factor: int,
) -> str:
    """sha256(...)[:32] hex — cùng row → cùng id → idempotent reupload.

    Lat/lon round 6 decimals (~10cm) để epsilon noise đầu vào CSV không tạo
    external_id khác (tránh user vô tình save file ở precision khác → duplicate).
    """
    raw = "|".join(
        [
            str(user_id),
            ts_iso,
            f"{latitude:.6f}",
            f"{longitude:.6f}",
            gateway_code,
            str(spreading_factor),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
