"""Credential encryption — MultiFernet.

Plan-auth-v1 §3.3 hidden: thuật toán mã hoá, key, format không lộ qua
interface `LinkingService`. Caller chỉ thấy `encrypt(plain) -> bytes` /
`decrypt(blob) -> plain`.

Quyết định:
  * Fernet (cryptography lib): AES-128-CBC + HMAC-SHA256 + timestamp +
    random IV. Authenticated encryption out-of-the-box. Algorithm chi tiết
    không đẩy ra interface — đổi thuật toán không break caller.
  * MultiFernet cho rotation: key đầu (newest) dùng encrypt; tất cả keys
    dùng decrypt fallback. Rotate = thêm key mới ở đầu list, giữ key cũ
    để decrypt blob cũ. Background re-encrypt sau (Step v2).

Credentials JSON-serialised TRƯỚC encrypt — caller pass `dict[str, str]`,
module này lo serialisation. Lý do: blob trên disk là single bytes; caller
không phải tự encode/decode JSON 2 phía.
"""

from __future__ import annotations

import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class CredentialCipher:
    """Encrypt/decrypt credential dict. Stateless modulo keys."""

    def __init__(self, keys: list[bytes]) -> None:
        if not keys:
            raise ValueError("CredentialCipher cần ít nhất 1 Fernet key")
        # MultiFernet: key đầu (index 0) = encrypt; toàn bộ list = decrypt thử.
        self._fernet = MultiFernet([Fernet(k) for k in keys])

    def encrypt(self, credentials: dict[str, str]) -> bytes:
        plain = json.dumps(credentials, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return self._fernet.encrypt(plain)

    def decrypt(self, blob: bytes) -> dict[str, str]:
        """Decrypt + parse JSON. Raise `InvalidToken` nếu ciphertext xấu hoặc
        không key nào trong list decrypt được (key bị rotate ra hết).
        """
        try:
            plain = self._fernet.decrypt(blob)
        except InvalidToken:
            raise
        data = json.loads(plain.decode("utf-8"))
        if not isinstance(data, dict):
            raise InvalidToken("Decrypted blob không phải JSON object")
        return {str(k): str(v) for k, v in data.items()}
