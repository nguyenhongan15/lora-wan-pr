"""
core/logging.py — Structured JSON logging theo chuẩn Observability.

Log ra stdout (tuân thủ 12-Factor Factor 11: Logs = Event Streams).
Mỗi log là 1 dòng JSON, dễ cho ELK / Grafana Loki query.

Mẫu:
  {"ts":"2026-04-19T10:00:00Z","lvl":"info","logger":"predict",
   "msg":"Train done","request_id":"abc-123","duration_ms":1234}
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from config import get_settings

# Context biến — gán request_id qua middleware, đọc lại trong formatter
_request_id_var: "contextvars.ContextVar[str]"

import contextvars
_request_id_var = contextvars.ContextVar("request_id", default="-")


def set_request_id(rid: str) -> None:
    _request_id_var.set(rid)


def get_request_id() -> str:
    return _request_id_var.get()


class JsonFormatter(logging.Formatter):
    """Format log record thành JSON 1-dòng."""

    # Các field chuẩn của LogRecord cần bỏ ra khỏi "extra"
    _STANDARD = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts":         datetime.now(timezone.utc).isoformat(),
            "lvl":        record.levelname.lower(),
            "logger":     record.name,
            "msg":        record.getMessage(),
            "request_id": _request_id_var.get(),
        }

        # Extra fields truyền qua logger.info("...", extra={"key": val})
        for k, v in record.__dict__.items():
            if k not in self._STANDARD and not k.startswith("_"):
                payload[k] = v

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging() -> None:
    """Gắn JsonFormatter vào root logger, in ra stdout."""
    settings = get_settings()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # Silence các lib ồn ào
    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
