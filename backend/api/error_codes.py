from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Dict, Optional

__all__ = [
    "ErrorCode",
    "is_safe_error_code",
    "build_error_payload",
]


_SAFE_ERROR_CODE_RE = re.compile(r"^[a-z0-9_]{1,80}$")


class ErrorCode(StrEnum):
    # Generic
    INTERNAL_ERROR = "internal_error"
    VALIDATION_ERROR = "validation_error"
    HTTP_ERROR = "http_error"

    # Auth
    INVALID_OR_EXPIRED_TOKEN = "invalid_or_expired_token"

    # Papers / exports
    PAPER_CREATE_FAILED = "paper_create_failed"
    PAPER_EXPORT_FAILED = "paper_export_failed"

    # Study materials
    CONVERT_MARKDOWN_TO_LATEX_FAILED = "convert_markdown_to_latex_failed"

    # Subjects / crawler
    SUBJECT_FILTERS_FAILED = "filters_failed"

    # OpenAI adapter legacy endpoints
    OPENAI_ADAPTER_CREATE_PAPER_FAILED = "create_paper_failed"


def is_safe_error_code(value: str) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return False
    return _SAFE_ERROR_CODE_RE.fullmatch(raw) is not None


def build_error_payload(
    *,
    code: str,
    message: str,
    details: Any,
    request_id: str,
    http_status: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Standard API error payload.

    - New keys: code/message/details/request_id (P0 requirement in nextstep #278)
    - Back-compat: keep FastAPI-style `detail` + our existing `{ error: { ... } }` envelope
      because the frontend parses it today.
    """

    normalized_code = str(code or "").strip() or str(ErrorCode.HTTP_ERROR)
    normalized_message = str(message or "").strip() or normalized_code
    rid = str(request_id or "").strip()

    payload: Dict[str, Any] = {
        "code": normalized_code,
        "message": normalized_message,
        "details": details,
        "request_id": rid,
        # Back-compat: many callers read `detail` (FastAPI default).
        "detail": details,
        # Back-compat: current frontend expects `{ error: { code, message, request_id } }`.
        "error": {
            "code": normalized_code,
            "message": normalized_message,
            "request_id": rid,
        },
    }
    if http_status is not None:
        payload["status"] = int(http_status)
    return payload

