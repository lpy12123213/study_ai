from __future__ import annotations

import math
import threading
from typing import Any, Dict, List

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)

_tiktoken_lock = threading.Lock()
_tiktoken_encoder = None
_tiktoken_encode_failed_logged = False
_tiktoken_import_failed_logged = False


def _get_tiktoken_encoder():
    global _tiktoken_encoder, _tiktoken_import_failed_logged
    if _tiktoken_encoder is not None:
        return _tiktoken_encoder
    with _tiktoken_lock:
        if _tiktoken_encoder is not None:
            return _tiktoken_encoder
        try:
            import tiktoken  # type: ignore

            _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
        except (ImportError, LookupError, ValueError):
            _tiktoken_encoder = None
            if not _tiktoken_import_failed_logged:
                _tiktoken_import_failed_logged = True
                logger.info("tiktoken_unavailable_using_heuristic_tokenizer", extra={"advice": "pip install tiktoken"})
        return _tiktoken_encoder


def tokenizer_backend() -> str:
    return "tiktoken" if _get_tiktoken_encoder() is not None else "heuristic"


def estimate_text_tokens(text: str) -> int:
    value = str(text or "")
    if not value:
        return 0
    enc = _get_tiktoken_encoder()
    if enc is not None and len(value) <= 50_000:
        try:
            return int(len(enc.encode(value)))
        except (RuntimeError, TypeError, UnicodeError, ValueError):
            global _tiktoken_encode_failed_logged
            if not _tiktoken_encode_failed_logged:
                _tiktoken_encode_failed_logged = True
                logger.warning("tiktoken_encode_failed_fallback", exc_info=True)
    cjk = 0
    for ch in value:
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0x3040 <= code <= 0x30FF or 0xAC00 <= code <= 0xD7AF:
            cjk += 1
    ratio = float(cjk) / float(len(value) or 1)
    return int(math.ceil(len(value) / 1.6)) if ratio >= 0.25 else int(math.ceil(len(value) / 4.0))


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        total += 6
        total += estimate_text_tokens(str(message.get("role") or ""))
        total += estimate_text_tokens(str(message.get("content") or ""))
    return int(total)
