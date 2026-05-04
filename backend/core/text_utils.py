from __future__ import annotations

from typing import Any


def clip_text(text: Any, max_chars: int, ellipsis: str = "…") -> str:
    """Return a stripped text preview capped to max_chars."""

    if max_chars <= 0:
        return ""
    s = str(text or "").strip()
    if not s:
        return ""
    if len(s) <= max_chars:
        return s
    marker = str(ellipsis or "")
    if not marker:
        return s[:max_chars].rstrip()
    return s[: max(0, max_chars - len(marker))].rstrip() + marker
