"""ChirpStack uplink → SurveyRecord adapter.

Pure function — không I/O, không DB. Sống ở application layer vì là
business mapping giữa external schema (ChirpStack) và domain.

Input: 1 uplink JSON (dict) theo schema ChirpStack v4 / v3 (rxInfo[] + txInfo).
Output: 0..N SurveyRecord (1 record cho mỗi rxInfo, vì 1 uplink có thể
        được nhiều gateway nhận).

Các trường hợp REJECT (không tạo record):
  * thiếu txInfo / SF / frequency   → không biết tham số radio
  * thiếu rxInfo (rỗng)             → không có gateway nào nhận
  * device GPS không hợp lệ         → không có toạ độ device để gắn vào điểm đo
  * rxInfo entry thiếu rssi/snr     → record đó bị bỏ, các entry khác vẫn ingest

Adapter PHẢI tolerant: 1 uplink xấu không làm cả batch fail. Reject reasons
trả về cho caller log/audit; ts.survey_quarantine vẫn nhận records pass.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..domain.survey import (
    RSSI_MAX_DBM,
    RSSI_MIN_DBM,
    SNR_MAX_DB,
    SNR_MIN_DB,
    SurveyRecord,
)

# ChirpStack encode SF qua chuỗi bandwidth/codeRate; SF nằm ở
# txInfo.modulation.lora.spreadingFactor (int).
_VALID_SF = frozenset({7, 8, 9, 10, 11, 12})

# Một số decoder gửi gnss_latitude dưới dạng signed int = degree * 1e7
# (Cayenne LPP / GPS payload). Heuristic: |x| > 360 → assume scaled.
_GNSS_SCALE_THRESHOLD = 360.0
_GNSS_SCALE = 1e7


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """Kết quả map 1 uplink. Có thể có 0..N records + reasons reject."""

    records: list[SurveyRecord] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


def _decode_gnss(raw: Any) -> float | None:
    """Trả độ (degrees) hoặc None nếu không hợp lệ.

    Hỗ trợ float trực tiếp và scaled-int (degree * 1e7).
    Loại 0/0 vì decoder thường trả 0 khi không fix được GPS.
    """
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v == 0.0:
        return None
    if abs(v) > _GNSS_SCALE_THRESHOLD:
        v = v / _GNSS_SCALE
    if not -90.0 <= v <= 180.0:  # cho phép cả lat & lon ở đây; check lại sau
        return None
    return v


def _parse_iso(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    # ChirpStack dùng ISO 8601 với offset; Python 3.12 fromisoformat hiểu được.
    try:
        # Một số biến thể có ".176011+00:00" — fromisoformat OK.
        # Một số có "Z" thay vì "+00:00".
        s = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def chirpstack_uplink_to_survey_records(uplink: dict[str, Any]) -> AdapterResult:
    """Map 1 ChirpStack uplink → list[SurveyRecord].

    KHÔNG resolve serving_gateway_id (cần DB); để application/webhook layer làm.
    Trả AdapterResult với records hợp lệ + lý do reject (nếu có).
    """
    rejected: list[str] = []

    # ── txInfo: lấy SF + frequency_mhz ───────────────────────────────────
    tx = uplink.get("txInfo")
    if not isinstance(tx, dict):
        return AdapterResult(rejected=["missing txInfo"])

    lora = (tx.get("modulation") or {}).get("lora") or {}
    sf_raw = lora.get("spreadingFactor")
    try:
        sf = int(sf_raw) if sf_raw is not None else None
    except (TypeError, ValueError):
        sf = None
    if sf not in _VALID_SF:
        return AdapterResult(rejected=[f"invalid spreadingFactor: {sf_raw!r}"])

    freq_hz_raw = tx.get("frequency")
    try:
        freq_mhz = float(freq_hz_raw) / 1e6 if freq_hz_raw else None
    except (TypeError, ValueError):
        freq_mhz = None
    if freq_mhz is None or freq_mhz <= 0:
        return AdapterResult(rejected=[f"invalid frequency: {freq_hz_raw!r}"])

    # ── device GPS từ object.gnss_* ──────────────────────────────────────
    obj = uplink.get("object") or {}
    dev_lat = _decode_gnss(obj.get("gnss_latitude"))
    dev_lon = _decode_gnss(obj.get("gnss_longitude"))
    if dev_lat is None or dev_lon is None:
        return AdapterResult(rejected=["missing/invalid device GPS"])
    if not -90.0 <= dev_lat <= 90.0 or not -180.0 <= dev_lon <= 180.0:
        return AdapterResult(rejected=[f"GPS out of range: {dev_lat},{dev_lon}"])

    # ── timestamp gốc của uplink ─────────────────────────────────────────
    uplink_time = _parse_iso(uplink.get("time")) or datetime.now(tz=UTC)

    device_info = uplink.get("deviceInfo") or {}
    device_id = device_info.get("devEui") or device_info.get("deviceName") or uplink.get("devEui")
    if isinstance(device_id, str):
        device_id = device_id[:128]  # match SurveyRecord constraint
    else:
        device_id = None

    # ── rxInfo: 1 record / gateway reception ─────────────────────────────
    rx_list = uplink.get("rxInfo")
    if not isinstance(rx_list, list) or not rx_list:
        return AdapterResult(rejected=["missing rxInfo"])

    records: list[SurveyRecord] = []
    for i, rx in enumerate(rx_list):
        if not isinstance(rx, dict):
            rejected.append(f"rxInfo[{i}] not object")
            continue

        rssi = rx.get("rssi")
        snr = rx.get("snr")
        try:
            rssi_dbm = float(rssi) if rssi is not None else None
            snr_db = float(snr) if snr is not None else None
        except (TypeError, ValueError):
            rejected.append(f"rxInfo[{i}] rssi/snr not numeric")
            continue
        if rssi_dbm is None or snr_db is None:
            rejected.append(f"rxInfo[{i}] missing rssi/snr")
            continue

        # SurveyRecord enforce range trong __post_init__; clip nhẹ ở đây
        # để 1 outlier không kill cả batch — log lý do.
        if not RSSI_MIN_DBM <= rssi_dbm <= RSSI_MAX_DBM:
            rejected.append(f"rxInfo[{i}] rssi {rssi_dbm} out of range")
            continue
        if not SNR_MIN_DB <= snr_db <= SNR_MAX_DB:
            rejected.append(f"rxInfo[{i}] snr {snr_db} out of range")
            continue

        # Timestamp ưu tiên gwTime của rxInfo này, fallback uplink time.
        ts = _parse_iso(rx.get("gwTime")) or uplink_time

        try:
            records.append(
                SurveyRecord(
                    timestamp=ts,
                    latitude=dev_lat,
                    longitude=dev_lon,
                    rssi_dbm=rssi_dbm,
                    snr_db=snr_db,
                    spreading_factor=sf,
                    frequency_mhz=freq_mhz,
                    device_id=device_id,
                    serving_gateway_id=None,  # resolve sau ở application/webhook
                )
            )
        except ValueError as e:
            rejected.append(f"rxInfo[{i}] domain reject: {e}")

    return AdapterResult(records=records, rejected=rejected)


def chirpstack_batch_to_survey_records(
    uplinks: Iterable[dict[str, Any]],
) -> AdapterResult:
    """Convenience: map nhiều uplink, gộp records + rejected reasons."""
    all_records: list[SurveyRecord] = []
    all_rejected: list[str] = []
    for idx, up in enumerate(uplinks):
        r = chirpstack_uplink_to_survey_records(up)
        all_records.extend(r.records)
        for reason in r.rejected:
            all_rejected.append(f"uplink[{idx}]: {reason}")
    return AdapterResult(records=all_records, rejected=all_rejected)
