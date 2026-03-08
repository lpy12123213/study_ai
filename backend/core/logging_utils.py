from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextvars import ContextVar
from typing import Any, Dict, Optional

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_client_ip_var: ContextVar[str] = ContextVar("client_ip", default="")


def set_request_id(request_id: str) -> str:
    rid = str(request_id or "").strip()
    _request_id_var.set(rid)
    return rid


def get_request_id() -> str:
    return str(_request_id_var.get() or "").strip()


def set_client_ip(client_ip: str) -> str:
    ip = str(client_ip or "").strip()
    _client_ip_var.set(ip)
    return ip


def get_client_ip() -> str:
    return str(_client_ip_var.get() or "").strip()


def _level_from_env() -> int:
    raw = str(os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    if raw in {"CRITICAL", "FATAL"}:
        return logging.CRITICAL
    if raw == "ERROR":
        return logging.ERROR
    if raw == "WARNING" or raw == "WARN":
        return logging.WARNING
    if raw == "DEBUG":
        return logging.DEBUG
    if raw == "NOTSET":
        return logging.NOTSET
    return logging.INFO


class JsonFormatter(logging.Formatter):
    _reserved = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id

        client_ip = get_client_ip()
        if client_ip:
            payload["client_ip"] = client_ip

        payload["src"] = {"module": record.module, "func": record.funcName, "line": record.lineno}

        extra: Dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in self._reserved or key.startswith("_"):
                continue
            extra[key] = value
        if extra:
            payload["extra"] = extra

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(*, force: bool = False) -> None:
    """Configure structured (JSON) logging for the backend process.

    - Default format is JSON (one line per record).
    - Set `LOG_FORMAT=text` to keep plain text logs.
    """

    root = logging.getLogger()
    if root.handlers and not force:
        return

    level = _level_from_env()
    fmt = str(os.getenv("LOG_FORMAT") or "json").strip().lower()
    if fmt not in {"json", "text"}:
        fmt = "json"

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(level)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(fmt="%(asctime)s %(levelname)s %(name)s: %(message)s"))

    root.handlers = [handler]
    root.setLevel(level)

    for noisy in ("httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

    # Uvicorn configures its own handlers before importing the app; force those
    # loggers to propagate to root so everything becomes JSON lines.
    for uv_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"):
        uv = logging.getLogger(uv_name)
        uv.handlers = []
        uv.propagate = True
        uv.setLevel(level)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(name or __name__)
