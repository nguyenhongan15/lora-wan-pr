"""gRPC-web transport — private helper cho ChirpStack adapter.

ChirpStack v4 public deployments thường chỉ expose gRPC-web qua nginx
(không có companion `chirpstack-rest-api`). gRPC native chạy HTTP/2 — httpx
hỗ trợ, nhưng nginx mặc định không proxy gRPC native trên 443; còn
gRPC-web chạy POST HTTP/1.1 framing → proxy như HTTP bình thường.

Framing (https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-WEB.md):

  Request body:
    [0x00 1B flag][len 4B BE][protobuf payload]

  Response body = concat của:
    [0x00 1B flag][len 4B BE][protobuf payload]   ← data frame(s)
    [0x80 1B flag][len 4B BE][http/1 trailers]    ← trailer frame (last)

  Trailers (text/plain, CRLF separated):
    grpc-status: <int>
    grpc-message: <str>

Module ẩn toàn bộ framing/trailer parsing — caller chỉ thấy `call(stub,
method, request) -> response` giống stub gRPC sync bình thường.
"""

from __future__ import annotations

from typing import TypeVar

import httpx
from google.protobuf.message import Message

from ..errors import SourceAuthError, SourceFetchError, SourceUnreachableError

# gRPC status codes — google.rpc.Code subset ta gặp thực tế ở adapter.
# Map đầy đủ ở https://grpc.io/docs/guides/status-codes/
_GRPC_OK = 0
_GRPC_PERMISSION_DENIED = 7
_GRPC_UNAUTHENTICATED = 16
_GRPC_UNAVAILABLE = 14
_GRPC_DEADLINE_EXCEEDED = 4

_FRAME_HEADER_LEN = 5
_TRAILER_FLAG = 0x80

_DEFAULT_TIMEOUT_S = 30.0

ResponseT = TypeVar("ResponseT", bound=Message)


class GrpcWebClient:
    """Thin gRPC-web client — 1 method `call`, không stateful gì khác.

    `verify=False` chỉ dùng cho server thiếu intermediate cert hoặc
    self-signed (xem comment ở Client.__init__ phía REST cũ — cùng lý do).
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        verify: bool = True,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout_s,
            verify=verify,
            # HTTP/1.1 bắt buộc cho gRPC-web (HTTP/2 = gRPC native, nginx
            # public thường không proxy đường đó). httpx default HTTP/1.1
            # rồi — set explicit để tránh upgrade ngẫu nhiên.
            http2=False,
        )

    def close(self) -> None:
        self._http.close()

    def call(
        self,
        *,
        service: str,
        method: str,
        request: Message,
        response_type: type[ResponseT],
        token: str,
    ) -> ResponseT:
        """POST 1 unary RPC. Service path = `/{service}/{method}`.

        Raises:
            SourceAuthError: gRPC UNAUTHENTICATED/PERMISSION_DENIED hoặc HTTP 401/403.
            SourceUnreachableError: network/timeout/UNAVAILABLE/DEADLINE_EXCEEDED.
            SourceFetchError: framing/parse lỗi hoặc grpc-status khác.
        """
        path = f"/{service}/{method}"
        payload = request.SerializeToString()
        body = _frame(0x00, payload)
        headers = {
            "content-type": "application/grpc-web+proto",
            "accept": "application/grpc-web+proto",
            "x-grpc-web": "1",
            "authorization": f"Bearer {token}",
            # grpc-timeout cùng giá trị httpx timeout — server có thể cancel
            # sớm hơn, ta cancel ở client khi timeout. Format: "<N><unit>"
            # với unit ∈ {H,M,S,m,u,n} — gửi giây.
            "grpc-timeout": f"{int(self._http.timeout.connect or _DEFAULT_TIMEOUT_S)}S",
        }

        try:
            resp = self._http.post(path, content=body, headers=headers)
        except httpx.RequestError as exc:
            raise SourceUnreachableError(f"{path} network error: {exc}") from exc

        # HTTP-level errors trước khi parse grpc frames. ChirpStack /
        # nginx có thể trả 404 (path sai) / 401 (TLS client cert), v.v.
        if resp.status_code in (401, 403):
            raise SourceAuthError(f"chirpstack rejected token ({resp.status_code})")
        if resp.status_code >= 500:
            raise SourceUnreachableError(f"chirpstack upstream {resp.status_code}")
        if resp.status_code != 200:
            raise SourceFetchError(f"{path} unexpected HTTP {resp.status_code}: {resp.text[:200]}")

        # Trailers có thể nằm trong HTTP/1.1 trailer headers (grpc-web text)
        # HOẶC trong trailer frame ở body (grpc-web+proto). ChirpStack/nginx
        # dùng body trailer → parse từ body. Fallback check header `grpc-status`
        # nếu server trả ở HTTP trailers (rare).
        data, trailer = _parse_frames(resp.content)

        # Trailer frame có thể empty nếu server trả grpc-status qua HTTP
        # trailer headers. httpx không auto-merge HTTP trailers vào resp.headers
        # cho HTTP/1.1 — phải đọc raw stream. Practical fallback: nếu data có
        # mà trailer rỗng, coi như OK (chirpstack-rest-api làm vậy).
        if trailer:
            status_code, message = _parse_trailer(trailer)
            _raise_for_grpc_status(path, status_code, message)
        else:
            header_status = resp.headers.get("grpc-status")
            if header_status is not None:
                status_code = int(header_status)
                message = resp.headers.get("grpc-message", "")
                _raise_for_grpc_status(path, status_code, message)

        # Empty data hợp lệ: response message với toàn field default (vd
        # ListDevicesResponse khi application không có device — total_count=0
        # + result=[] đều default → protobuf serialize = 0 bytes). Đừng raise
        # ở đây; ParseFromString(b'') trả message rỗng OK.
        result = response_type()
        try:
            result.ParseFromString(data)
        except Exception as exc:
            raise SourceFetchError(f"{path} protobuf parse error: {exc}") from exc
        return result


# ── Framing helpers (module-private) ──────────────────────────────────────


def _frame(flag: int, payload: bytes) -> bytes:
    return bytes([flag]) + len(payload).to_bytes(4, "big") + payload


def _parse_frames(body: bytes) -> tuple[bytes, bytes]:
    """Tách body thành (data_concat, trailer_bytes).

    Server có thể gửi nhiều data frame trước trailer. Ta concat tất cả data
    frames thành 1 message bytes (protobuf message types ta dùng là unary
    response, nên thực tế chỉ có 1 data frame — concat defensive).
    """
    data_chunks: list[bytes] = []
    trailer = b""
    offset = 0
    while offset < len(body):
        if offset + _FRAME_HEADER_LEN > len(body):
            raise SourceFetchError("grpc-web frame truncated (header)")
        flag = body[offset]
        length = int.from_bytes(body[offset + 1 : offset + 5], "big")
        offset += _FRAME_HEADER_LEN
        if offset + length > len(body):
            raise SourceFetchError("grpc-web frame truncated (payload)")
        chunk = body[offset : offset + length]
        offset += length
        if flag & _TRAILER_FLAG:
            trailer = chunk
            break
        data_chunks.append(chunk)
    return b"".join(data_chunks), trailer


def _parse_trailer(trailer: bytes) -> tuple[int, str]:
    """Trailer = CRLF-separated `key: value` lines. Case-insensitive keys.

    Trả (grpc-status, grpc-message). Default status 0 nếu thiếu (defensive —
    treat as OK).
    """
    status = _GRPC_OK
    message = ""
    text = trailer.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key_lower = key.strip().lower()
        value_str = value.strip()
        if key_lower == "grpc-status":
            try:
                status = int(value_str)
            except ValueError:
                status = -1
        elif key_lower == "grpc-message":
            message = value_str
    return status, message


def _raise_for_grpc_status(path: str, status_code: int, message: str) -> None:
    if status_code == _GRPC_OK:
        return
    detail = f"{path} grpc-status={status_code}"
    if message:
        detail = f"{detail} {message[:200]}"
    if status_code in (_GRPC_UNAUTHENTICATED, _GRPC_PERMISSION_DENIED):
        raise SourceAuthError(detail)
    if status_code in (_GRPC_UNAVAILABLE, _GRPC_DEADLINE_EXCEEDED):
        raise SourceUnreachableError(detail)
    raise SourceFetchError(detail)
