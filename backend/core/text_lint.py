from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"(?<!\{)\{[A-Za-z_][A-Za-z0-9_]{1,40}\}(?!\})")
# 数学区间：$$...$$ 与 \[...\] 可跨行，行内 $...$ 不跨行。占位符检查前先剥离，
# 避免 LaTeX 环境参数（\begin{pmatrix}、\operatorname{span} 等）被误判为未填占位符。
_MATH_SPAN_RE = re.compile(
    r"\$\$.+?\$\$"        # $$...$$ 独立公式（可跨行）
    r"|\\\[.+?\\\]"       # \[...\] 独立公式（可跨行）
    r"|\$[^\$\n]+?\$",    # $...$ 行内公式（不跨行）
    re.S,
)
_UNESCAPED_SINGLE_DOLLAR_RE = re.compile(r"(?<!\\)(?<!\$)\$(?!\$)")
_UNESCAPED_DOUBLE_DOLLAR_RE = re.compile(r"(?<!\\)\$\$")
_CODE_FENCE_RE = re.compile(r"(?m)^```")
_HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
# 句读终止符：中英文句末标点 + 常见闭合引号/括号（用于判断文末是否被截断）。
_TERMINAL_PUNCT = frozenset("。！？!?；;：:….．”’\"')）》」』】]}")


def _has_heading_with_empty_body(raw: str) -> bool:
    lines = raw.splitlines()
    headings = [
        (index, len(match.group(1)))
        for index, line in enumerate(lines)
        if (match := _HEADING_RE.match(line))
    ]
    for position, (line_no, level) in enumerate(headings):
        end = len(lines)
        for next_no, next_level in headings[position + 1 :]:
            if next_level <= level:
                end = next_no
                break
        body = lines[line_no + 1 : end]
        if all(not line.strip() or _HEADING_RE.match(line) for line in body):
            return True
    return False


def _ends_mid_sentence(raw: str, *, fence_count: int, display_math_count: int) -> bool:
    tail = raw.rstrip()
    if not tail:
        return False
    if fence_count % 2 == 1 or display_math_count % 2 == 1:
        return True
    if tail.endswith("```") and fence_count >= 2:
        return False  # 以完整代码块收尾，不算截断
    if tail.endswith("$$") and display_math_count >= 2:
        return False  # 以完整独立公式收尾，不算截断
    return tail[-1] not in _TERMINAL_PUNCT


def lint_text(text: Any) -> list[str]:
    """Return lightweight content-quality flags for generated Markdown/text."""

    raw = str(text or "")
    if not raw.strip():
        return []

    flags: list[str] = []
    # 仅占位符检查在剥离数学区间后的文本上执行；其余检查仍对原文执行。
    if _PLACEHOLDER_RE.search(_MATH_SPAN_RE.sub("", raw)):
        flags.append("unresolved_placeholder")
    if len(_UNESCAPED_SINGLE_DOLLAR_RE.findall(raw)) % 2 == 1:
        flags.append("unbalanced_inline_math")
    fence_count = len(_CODE_FENCE_RE.findall(raw))
    if fence_count % 2 == 1:
        flags.append("unclosed_code_fence")
    if re.search(r"(?m)^\s*\|[^|\n]+\|\s*$", raw):
        flags.append("suspicious_markdown_table")
    display_math_count = len(_UNESCAPED_DOUBLE_DOLLAR_RE.findall(raw))
    if display_math_count % 2 == 1:
        flags.append("unclosed_display_math")
    if _has_heading_with_empty_body(raw):
        flags.append("heading_with_empty_body")
    if _ends_mid_sentence(raw, fence_count=fence_count, display_math_count=display_math_count):
        flags.append("eof_mid_sentence")
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
