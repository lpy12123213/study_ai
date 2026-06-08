from __future__ import annotations

import re
from typing import Any


def _has_unclosed_code_fence(text: str) -> bool:
    return len(re.findall(r"(?m)^```", text or "")) % 2 == 1


def _has_unbalanced_inline_math(text: str) -> bool:
    raw = str(text or "")
    if not raw:
        return False
    # Count unescaped single-dollar math markers; leave display $$ pairs alone.
    singles = re.findall(r"(?<!\\)(?<!\$)\$(?!\$)", raw)
    return len(singles) % 2 == 1


def repair_incomplete_markdown(text: str) -> str:
    """Best-effort repair for snippets cut through Markdown structures."""

    raw = str(text or "").rstrip()
    if not raw:
        return ""
    suffixes: list[str] = []
    if _has_unbalanced_inline_math(raw):
        suffixes.append("$")
    if _has_unclosed_code_fence(raw):
        suffixes.append("\n```")
    if not suffixes:
        return raw
    return raw + "".join(suffixes)


def clip_text(text: Any, max_chars: int, ellipsis: str = "…", *, repair_markdown: bool = True) -> str:
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
        clipped = s[:max_chars].rstrip()
        return repair_incomplete_markdown(clipped) if repair_markdown else clipped
    clipped = s[: max(0, max_chars - len(marker))].rstrip() + marker
    return repair_incomplete_markdown(clipped) if repair_markdown else clipped
