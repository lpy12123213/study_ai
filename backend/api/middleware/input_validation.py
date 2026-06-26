from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.core.logging_utils import get_logger, get_request_id
from backend.core.settings import env_int

logger = get_logger(__name__)


@dataclass(frozen=True)
class InputLimits:
    max_body_bytes: int = 2_000_000
    # Keep this higher than typical Pydantic field constraints, otherwise we'd
    # truncate and bypass the app's explicit `max_length=...` validation.
    max_string_length: int = 250_000
    max_array_size: int = 400
    max_object_keys: int = 400
    max_nested_depth: int = 20
    strip_html_tags: bool = True


_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_DANGEROUS_HTML_RE = re.compile(r"<\s*(script|iframe|object|embed|link|style)\b", flags=re.I)
_DANGEROUS_PROTO_RE = re.compile(r"javascript\s*:", flags=re.I)


def _truthy(raw: str) -> bool:
    s = (raw or "").strip().lower()
    return s in {"1", "true", "yes", "y", "on"}


def limits_from_env() -> InputLimits:
    strip_html_raw = os.getenv("INPUT_STRIP_HTML_TAGS")
    strip_html = True if strip_html_raw is None else _truthy(strip_html_raw)

    return InputLimits(
        max_body_bytes=env_int("INPUT_MAX_BODY_BYTES", InputLimits.max_body_bytes),
        max_string_length=env_int("INPUT_MAX_STRING_LENGTH", InputLimits.max_string_length),
        max_array_size=env_int("INPUT_MAX_ARRAY_SIZE", InputLimits.max_array_size),
        max_object_keys=env_int("INPUT_MAX_OBJECT_KEYS", InputLimits.max_object_keys),
        max_nested_depth=env_int("INPUT_MAX_NESTED_DEPTH", InputLimits.max_nested_depth),
        strip_html_tags=strip_html,
    )


class InputValidationMiddleware(BaseHTTPMiddleware):
    """Best-effort request JSON sanitization.

    This middleware aims to:
    - Clamp extreme payload sizes (body bytes / nesting depth / container sizes).
    - Normalize strings (strip dangerous HTML, clamp length).

    It only applies to JSON bodies (Content-Type contains `application/json`).
    """

    def __init__(self, app: Any, *, limits: Optional[InputLimits] = None) -> None:
        super().__init__(app)
        self._limits = limits or limits_from_env()

    def _sanitize_str(self, value: str) -> str:
        s = str(value or "")
        # Drop NUL and other low control chars except common whitespace.
        s = "".join(ch for ch in s if ch in {"\n", "\r", "\t"} or ord(ch) >= 32)

        if _DANGEROUS_HTML_RE.search(s) or _DANGEROUS_PROTO_RE.search(s):
            raise ValueError("dangerous_html")

        if self._limits.strip_html_tags and ("<" in s and ">" in s):
            # Only strip real tags like "<div ...>" not math comparisons like "x<y".
            s = _HTML_TAG_RE.sub("", s)

        if _DANGEROUS_HTML_RE.search(s) or _DANGEROUS_PROTO_RE.search(s):
            raise ValueError("dangerous_html")

        if self._limits.max_string_length > 0 and len(s) > self._limits.max_string_length:
            s = s[: self._limits.max_string_length]
        return s

    def _sanitize(self, value: Any, *, depth: int) -> Any:
        if depth > self._limits.max_nested_depth:
            raise ValueError("payload_too_deep")

        if isinstance(value, str):
            return self._sanitize_str(value)

        if isinstance(value, list):
            if self._limits.max_array_size > 0 and len(value) > self._limits.max_array_size:
                raise ValueError("payload_array_too_large")
            return [self._sanitize(v, depth=depth + 1) for v in value]

        if isinstance(value, dict):
            if self._limits.max_object_keys > 0 and len(value) > self._limits.max_object_keys:
                raise ValueError("payload_object_too_large")
            out: Dict[str, Any] = {}
            for k, v in value.items():
                key = str(k)
                if self._limits.max_string_length > 0 and len(key) > 200:
                    key = key[:200]
                out[key] = self._sanitize(v, depth=depth + 1)
            return out

        # Numbers/bools/null/etc: keep unchanged.
        return value

    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            path = str(request.url.path or "")
        except (AttributeError, RuntimeError, ValueError):
            path = ""

        if not path.startswith("/api/"):
            return await call_next(request)

        method = (request.method or "").upper()
        if method not in {"POST", "PUT", "PATCH"}:
            return await call_next(request)

        ctype = str(request.headers.get("content-type") or "").lower()
        if "application/json" not in ctype:
            return await call_next(request)

        def _err(status_code: int, detail: str) -> JSONResponse:
            rid = get_request_id() or ""
            payload: Dict[str, Any] = {"detail": detail}
            if rid:
                payload["error"] = {"code": detail, "message": detail, "request_id": rid}
            else:
                payload["error"] = {"code": detail, "message": detail}
            return JSONResponse(status_code=int(status_code), content=payload)

        try:
            body = await request.body()
        except (OSError, RuntimeError):
            return _err(400, "invalid_body")

        if not body:
            return await call_next(request)

        if self._limits.max_body_bytes > 0 and len(body) > self._limits.max_body_bytes:
            return _err(413, "payload_too_large")

        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _err(400, "invalid_json")

        try:
            sanitized = self._sanitize(data, depth=0)
        except ValueError as exc:
            code = str(exc) or "invalid_payload"
            return _err(400, code)
        except (AttributeError, RecursionError, TypeError):
            logger.warning("input_sanitize_failed", exc_info=True)
            return _err(400, "invalid_payload")

        try:
            new_body = json.dumps(sanitized, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            return _err(400, "invalid_payload")

        # Starlette caches body in `request._body` after `.body()`; override so downstream sees sanitized input.
        try:
            request._body = new_body  # type: ignore[attr-defined]
        except Exception:
            # If this fails, still proceed (best-effort).
            logger.warning(
                "input_validation_body_override_failed",
                extra={"method": str(getattr(request, "method", "") or ""), "path": str(getattr(request.url, "path", "") or "")},
                exc_info=True,
            )

        return await call_next(request)
