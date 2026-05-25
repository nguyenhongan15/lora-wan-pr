"""CSV/JSON survey upload — personal-only hoặc community contribution.

Plan community-data-contribution §4. User upload file mỗi dòng/object = 1
reading (lat/lng/timestamp/rssi/snr/sf/gateway_code). Endpoint nhận multipart,
parse ở backend (KHÔNG trust FE đã validate), ghi quarantine với provenance
`source_type='csv_upload'` + `contributor_user_id=current_user.id`.

Hai định dạng được hỗ trợ:
  * CSV — header chuẩn (timestamp, latitude, longitude, rssi_dbm, snr_db,
    spreading_factor, gateway_code; tuỳ chọn frequency_mhz, device_id).
  * JSON — auto-detect 2 dạng:
      - Format A: array các object cùng schema với CSV (1 object = 1 row).
      - Format C: webhook payload từ TTN v3 (`uplink_message`) hoặc
        ChirpStack v4 (`rxInfo`). 1 event → N rows tương ứng N gateway thấy
        uplink trong `rx_metadata`/`rxInfo`.

`submit_to_community` checkbox quyết định promotion:
  * false → record dừng ở quarantine, scope theo user — chỉ chính user xem
    được qua /me/measurements (mode='self'). KHÔNG bao giờ promote.
  * true → set `submitted_for_community=true`, chạy TrustValidator pipeline
    (L1 bbox + gateway + L2 ITU physics, threshold 15 dB cố định). Pass →
    set `review_status='pending_review'` chờ admin duyệt thủ công (migration
    0018). Fail → ghi `reject_reason`, vẫn ở quarantine.

Idempotency: external_id = sha256(user_id + ts_iso + lat + lng + gateway_code
+ sf)[:32]. Cùng row CSV reupload → cùng external_id → UNIQUE PARTIAL
`(timestamp, source_type, external_id)` chặn duplicate insert. User có thể
reupload an toàn (vd sửa typo 1 dòng rồi re-submit).

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
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from ...application.identity import EmailNotVerifiedError, User
from ...application.repositories import GatewayDirectory, SurveyIngest
from ...application.trust import (
    TrustValidator,
    UnknownContributorError,
    delete_csv_batch_for_uploader,
    fetch_csv_stats_for_uploader,
    list_csv_batches_for_uploader,
    mark_and_promote_csv_batch_for_uploader,
    promote_pending_for_uploader,
)
from ...config import get_settings
from ...domain.coverage import Gateway, GatewayId
from ...domain.survey import SurveyBatch, SurveyRecord, UploaderId
from ..deps import (
    _engine,
    current_user,
    gateway_directory,
    survey_repository,
    trust_validator,
)
from ..rate_limit import limiter
from ..schemas import (
    CsvBatchDeleteResponse,
    CsvPromoteResponse,
    CsvUploadBatch,
    CsvUploadBatchList,
    CsvUploadResponse,
    CsvUploadStats,
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

_REQUIRED_COLUMNS = (
    "timestamp",
    "latitude",
    "longitude",
    "rssi_dbm",
    "snr_db",
    "spreading_factor",
    "gateway_code",
)
_SOURCE_TYPE = "csv_upload"


@router.post(
    "/csv",
    response_model=CsvUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload CSV survey measurements (personal hoặc community)",
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
    trust: Annotated[TrustValidator, Depends(trust_validator)],
    file: Annotated[UploadFile, File(description="CSV hoặc JSON (UTF-8)")],
    submit_to_community: Annotated[
        bool, Form(description="True = qua TrustValidator → ts.survey_training nếu pass")
    ] = False,
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

    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    is_json = filename.endswith(".json") or content_type.startswith("application/json")

    if is_json:
        parsed, parse_rejected_reasons = _parse_json(text, user_id=user.id, directory=directory)
    else:
        parsed, parse_rejected_reasons = _parse_csv(
            io.StringIO(text), user_id=user.id, directory=directory
        )
    parsed_count = len(parsed)
    parse_rejected_count = len(parse_rejected_reasons)

    if parsed_count == 0:
        return CsvUploadResponse(
            parsed_count=0,
            parse_rejected_count=parse_rejected_count,
            parse_rejected_reasons=parse_rejected_reasons[:50],
            inserted_count=0,
            promoted_count=0,
            promote_rejected_count=0,
            promote_rejected_by_reason={},
        )

    records = [p.record for p in parsed]
    external_ids: list[str | None] = [p.external_id for p in parsed]
    record_ids = [uuid4() for _ in parsed]
    batch = SurveyBatch(uploader_id=UploaderId(user.id), records=records)

    # `since` = thời điểm NGAY TRƯỚC khi write_quarantine. promote_pending_for_uploader
    # filter `uploaded_at >= since` để bỏ qua rows cũ của user (đã upload trước,
    # có thể đang ở pending từ lần trước nhưng không thuộc batch này).
    since = datetime.now(UTC)

    inserted_count = repo.write_quarantine_idempotent(
        batch,
        record_ids,
        external_ids=external_ids,
        source_type=_SOURCE_TYPE,
        linked_source_id=None,
        contributor_user_id=user.id,
        submitted_for_community=submit_to_community,
    )

    promoted_count = 0
    promote_rejected_count = 0
    promote_rejected_by_reason: dict[str, int] = {}

    if submit_to_community and inserted_count > 0:
        with _engine().begin() as conn:
            try:
                contributor = trust.load_contributor(conn, user.id)
            except UnknownContributorError:
                logger.warning(
                    "csv_upload_promote_skipped_unknown_user",
                    user_id=str(user.id),
                )
            else:
                result = promote_pending_for_uploader(
                    conn,
                    trust,
                    contributor,
                    uploader_id=user.id,
                    since=since,
                )
                promoted_count = result.accepted
                promote_rejected_count = result.rejected
                promote_rejected_by_reason = result.by_reason

    logger.info(
        "csv_upload_ingested",
        user_id=str(user.id),
        submit_to_community=submit_to_community,
        parsed=parsed_count,
        parse_rejected=parse_rejected_count,
        inserted=inserted_count,
        promoted=promoted_count,
        promote_rejected=promote_rejected_count,
        trace_id=getattr(request.state, "trace_id", None),
    )

    return CsvUploadResponse(
        parsed_count=parsed_count,
        parse_rejected_count=parse_rejected_count,
        parse_rejected_reasons=parse_rejected_reasons[:50],
        inserted_count=inserted_count,
        promoted_count=promoted_count,
        promote_rejected_count=promote_rejected_count,
        promote_rejected_by_reason=promote_rejected_by_reason,
    )


@router.get(
    "/csv/stats",
    response_model=CsvUploadStats,
    summary="Tổng quan dữ liệu CSV của user (tổng / pending / promoted / rejected)",
)
async def csv_stats(
    user: Annotated[User, Depends(current_user)],
) -> CsvUploadStats:
    with _engine().begin() as conn:
        stats = fetch_csv_stats_for_uploader(conn, user.id)
    return CsvUploadStats(
        total=stats.total,
        pending=stats.pending,
        pending_review=stats.pending_review,
        promoted=stats.promoted,
        rejected=stats.rejected,
    )


@router.post(
    "/csv/batches/promote",
    response_model=CsvPromoteResponse,
    status_code=status.HTTP_200_OK,
    summary="Đóng góp 1 file CSV cụ thể cho cộng đồng — chạy TrustValidator",
    responses={
        400: {"description": "uploaded_at không phải ISO 8601"},
        401: {"description": "Chưa đăng nhập"},
        403: {"description": "Chưa xác thực email"},
        429: {"description": "Rate limit exceeded"},
    },
)
@limiter.limit(_settings.me_csv_upload_rate_limit)
async def promote_csv_batch(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    trust: Annotated[TrustValidator, Depends(trust_validator)],
    uploaded_at: str,
) -> CsvPromoteResponse:
    """Mark + validator-loop CHỈ rows của 1 batch (1 lần upload = 1 file).

    Query param `uploaded_at` (ISO 8601) lấy nguyên từ GET /csv/batches để
    match microsecond chính xác. UI gọi từ row trong bảng "Các file đã upload"
    trên card CsvContributeCard.
    """
    if not user.email_verified:
        raise EmailNotVerifiedError("Cần xác thực email trước khi đóng góp dữ liệu cho cộng đồng")
    try:
        parsed_ts = datetime.fromisoformat(uploaded_at)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"uploaded_at không phải ISO 8601: {uploaded_at}",
        ) from exc
    if parsed_ts.tzinfo is None:
        parsed_ts = parsed_ts.replace(tzinfo=UTC)

    with _engine().begin() as conn:
        try:
            contributor = trust.load_contributor(conn, user.id)
        except UnknownContributorError as exc:
            raise HTTPException(status_code=401, detail="Tài khoản không tồn tại") from exc
        result = mark_and_promote_csv_batch_for_uploader(
            conn,
            trust,
            contributor,
            uploader_id=user.id,
            uploaded_at=parsed_ts,
        )

    logger.info(
        "csv_batch_promote_invoked",
        user_id=str(user.id),
        uploaded_at=uploaded_at,
        promoted=result.accepted,
        promote_rejected=result.rejected,
        trace_id=getattr(request.state, "trace_id", None),
    )

    return CsvPromoteResponse(
        promoted_count=result.accepted,
        promote_rejected_count=result.rejected,
        promote_rejected_by_reason=result.by_reason,
    )


@router.get(
    "/csv/batches",
    response_model=CsvUploadBatchList,
    summary="Danh sách các file CSV user đã upload (group by uploaded_at)",
)
async def list_csv_batches(
    user: Annotated[User, Depends(current_user)],
) -> CsvUploadBatchList:
    with _engine().begin() as conn:
        batches = list_csv_batches_for_uploader(conn, user.id)
    return CsvUploadBatchList(
        items=[
            CsvUploadBatch(
                uploaded_at=b.uploaded_at,
                total=b.total,
                pending=b.pending,
                pending_review=b.pending_review,
                promoted=b.promoted,
                rejected=b.rejected,
            )
            for b in batches
        ]
    )


@router.delete(
    "/csv/batches",
    response_model=CsvBatchDeleteResponse,
    summary="Xoá 1 batch CSV (theo uploaded_at) — cascade cả training nếu đã promote",
    responses={
        400: {"description": "uploaded_at không phải ISO 8601"},
        401: {"description": "Chưa đăng nhập"},
        404: {"description": "Batch không tồn tại / không thuộc user"},
    },
)
async def delete_csv_batch(
    user: Annotated[User, Depends(current_user)],
    uploaded_at: str,
) -> CsvBatchDeleteResponse:
    """Query param `uploaded_at` (ISO 8601). FE truyền nguyên giá trị nhận từ
    GET /csv/batches để đảm bảo match chính xác microsecond."""
    try:
        parsed_ts = datetime.fromisoformat(uploaded_at)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"uploaded_at không phải ISO 8601: {uploaded_at}",
        ) from exc
    if parsed_ts.tzinfo is None:
        parsed_ts = parsed_ts.replace(tzinfo=UTC)

    with _engine().begin() as conn:
        deleted = delete_csv_batch_for_uploader(conn, uploader_id=user.id, uploaded_at=parsed_ts)

    if deleted == 0:
        raise HTTPException(status_code=404, detail="Batch không tồn tại")

    logger.info(
        "csv_batch_deleted",
        user_id=str(user.id),
        uploaded_at=uploaded_at,
        deleted=deleted,
    )
    return CsvBatchDeleteResponse(deleted_count=deleted)


# ── parsing helpers ───────────────────────────────────────────────────────


class _ParsedRow:
    __slots__ = ("external_id", "record")

    def __init__(self, record: SurveyRecord, external_id: str) -> None:
        self.record = record
        self.external_id = external_id


def _parse_csv(
    text_io: io.StringIO,
    *,
    user_id: UUID,
    directory: GatewayDirectory,
) -> tuple[list[_ParsedRow], list[str]]:
    """Parse CSV → (parsed rows, rejected reasons với line number).

    KHÔNG raise — bad rows skip cùng reason text; caller bao gồm reasons trong
    response để FE hiển thị "dòng N: lý do" cho user sửa.
    """
    reader = csv.DictReader(text_io)
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="File không có header")

    missing = [c for c in _REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Thiếu cột bắt buộc: {', '.join(missing)}",
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

        try:
            record, external_id = _build_record(
                row, user_id=user_id, directory_cache=gw_cache, directory=directory
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
    snr = _parse_float(row.get("snr_db"), "snr_db")
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
        row = _stringify_row(item)
        try:
            record, external_id = _build_record(
                row, user_id=user_id, directory_cache=gw_cache, directory=directory
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
