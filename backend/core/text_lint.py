from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"(?<!\{)\{[A-Za-z_][A-Za-z0-9_]{1,40}\}(?!\})")
_UNESCAPED_SINGLE_DOLLAR_RE = re.compile(r"(?<!\\)(?<!\$)\$(?!\$)")


def lint_text(text: Any) -> list[str]:
    """Return lightweight content-quality flags for generated Markdown/text."""

    raw = str(text or "")
    if not raw.strip():
        return []

    flags: list[str] = []
    if _PLACEHOLDER_RE.search(raw):
        flags.append("unresolved_placeholder")
    if len(_UNESCAPED_SINGLE_DOLLAR_RE.findall(raw)) % 2 == 1:
        flags.append("unbalanced_inline_math")
    if len(re.findall(r"(?m)^```", raw)) % 2 == 1:
        flags.append("unclosed_code_fence")
    if re.search(r"(?m)^\s*\|[^|\n]+\|\s*$", raw):
        flags.append("suspicious_markdown_table")
    return flags


def lint_many(*parts: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        for flag in lint_text(part):
            if flag in seen:
                continue
            seen.add(flag)
            out.append(flag)
    return out
