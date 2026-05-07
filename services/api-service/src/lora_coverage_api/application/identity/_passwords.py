"""Password hashing — bcrypt direct (passlib bị bỏ).

Plan-auth-v1 §3.1 hidden: thuật toán + work factor không lộ ra interface.
Caller chỉ thấy `hash_password(plain) -> str` / `verify_password(plain, hashed) -> bool`.

Quyết định:
  * bcrypt direct (không passlib): passlib 1.7.4 unmaintained + xung đột với
    bcrypt >= 4.1 (`__about__` attribute removed). Direct binding ngắn gọn,
    không có thứ tự cần migrate sau này.
  * Work factor 12 = standard 2024 cho web auth (~250ms/hash CPU desktop).
  * bcrypt 4.x raise hard nếu password > 72 byte → caller giới hạn ở schema
    layer (RegisterRequest max_length=128 chars; phần lớn UTF-8 sẽ < 72
    bytes nhưng kẻ cố tình đẩy nhiều multi-byte ký tự sẽ bị router 422
    hoặc bcrypt raise tại đây — chấp nhận, không silent-truncate vì
    truncate âm thầm = bug security mode).
"""

from __future__ import annotations

import bcrypt

_ROUNDS = 12


def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt(rounds=_ROUNDS)
    hashed = bcrypt.hashpw(plain.encode("utf-8"), salt)
    return hashed.decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time compare. Trả False thay vì raise nếu hash format lạ."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False
