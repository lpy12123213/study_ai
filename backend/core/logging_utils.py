from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from contextvars import ContextVar
from typing import Any, Dict, Optional

from backend.core.secrets import SecretString

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


def get_trace_id() -> str:
    """Best-effort OpenTelemetry trace id (32 hex chars).

    This helper is intentionally optional: the backend runs fine without
    OpenTelemetry installed/enabled.
    """

    try:
        from opentelemetry import trace  # type: ignore

        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx and getattr(ctx, "trace_id", 0):
            return f"{int(ctx.trace_id):032x}"
    except Exception:
        return ""
    return ""


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


_SENSITIVE_KEY_RE = re.compile(r"(?i)(api[_-]?key|authorization|token|secret|password|passwd|cookie|set-cookie)")
# Mask common auth header formats.
_BEARER_RE = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9_.-]{10,})")
# Mask typical "api_key=..." / "token: ..." fragments that may show up in logs.
_KV_SECRET_RE = re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*([^\s,;]+)")


def _is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY_RE.search(str(key or "")))


def _scrub_text(text: str) -> str:
    raw = str(text or "")
    if not raw:
        return ""
    raw = _BEARER_RE.sub("Bearer ****", raw)
    raw = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}=****", raw)
    return raw


def _sanitize_value(value: Any, *, depth: int = 0) -> Any:  # noqa: ANN401
    if depth > 8:
        return "<max_depth>"
    if isinstance(value, SecretString):
        return str(value)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            ks = str(k)
            if _is_sensitive_key(ks):
                out[ks] = "****"
            else:
                out[ks] = _sanitize_value(v, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(v, depth=depth + 1) for v in list(value)[:200]]
    if isinstance(value, str):
        return _scrub_text(value)
    return value


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
            "msg": _scrub_text(record.getMessage()),
        }

        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id

        client_ip = get_client_ip()
        if client_ip:
            payload["client_ip"] = client_ip

        trace_id = get_trace_id()
        if trace_id:
            payload["trace_id"] = trace_id

        payload["src"] = {"module": record.module, "func": record.funcName, "line": record.lineno}

        extra: Dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in self._reserved or key.startswith("_"):
                continue
            extra[key] = value
        if extra:
            payload["extra"] = _sanitize_value(extra)

        if record.exc_info:
            payload["exc"] = _scrub_text(self.formatException(record.exc_info))

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
