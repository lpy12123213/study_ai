"""Deterministic assembler for the author-agent study materials pipeline.

Replaces ``[[FILL:<id>]]`` and ``[[FIG:<n>]]`` placeholders in the backbone with the
generated section bodies and figure references, renders the collected bibliography
as footnote definitions (``[^n]: title — url``, matching the inline ``[^n]``
citation markers used by section prose), appends a closing footer so the document
never ends mid-sentence, and rejects machine fallback notes before they leak into
the final prose (the legacy ``study_archive.py`` defect where "未成功使用模型生成"
notes reached readers). No LLM is involved in this module.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

# 占位符 id 字符集须覆盖蓝图合法小节 id（含下划线，见 blueprint.SECTION_ID_RE）：
# 真实缺陷——LLM 产出 s0_frontmatter 之类下划线 id 时，旧字符集不含 _，占位符
# 既不被替换也不计入 missing，静默残留成稿。
FILL_RE = re.compile(r"\[\[FILL:([A-Za-z0-9_\-]+)\]\]")
FIG_RE = re.compile(r"\[\[FIG:(\d+)\]\]")
_FALLBACK_LEAK_RE = re.compile(r"未成功使用模型生成|兜底内容|source=llm_|退回到摘要")
_PLACEHOLDER_TOKEN_RE = re.compile(r"\[\[(?:FILL:[A-Za-z0-9_\-]+|FIG:\d+)\]\]")
_HEADING_RE = re.compile(r"^(#{1,6})\s+\S")

# 收尾行：以句读终止符结束，消除 eof_mid_sentence lint（不用斜体标记，避免末尾 * 被判定截断）。
CLOSING_FOOTER = "本资料由作者代理生成，仅供学习参考。"


class AssemblyError(ValueError):
    """Raised when the backbone cannot be assembled into the final document.

    ``code`` and fragment metadata let the author pipeline repair the actual
    failure instead of parsing a human-readable exception string as if every
    assembly error were a comma-separated missing-section list.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "assembly_failed",
        missing: List[str] | None = None,
        fragment: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.missing = list(missing or [])
        self.fragment = fragment


def _check_leak(text: str, *, fragment: str) -> None:
    if has_fallback_note(text):
        raise AssemblyError(
            "fallback note leaked into content",
            code="fallback_leak",
            fragment=fragment,
        )


def has_fallback_note(text: str) -> bool:
    return bool(_FALLBACK_LEAK_RE.search(str(text or "")))


def strip_fallback_notes(text: str) -> str:
    """Remove whole machine-fallback note lines from a backbone repair attempt."""

    lines: List[str] = []
    for line in str(text or "").splitlines():
        if not has_fallback_note(line):
            lines.append(line)
            continue
        # Preserve any structural marker that an LLM accidentally placed on the
        # same line as its machine note; dropping the line would silently remove
        # a required section/figure from the backbone.
        lines.extend(_PLACEHOLDER_TOKEN_RE.findall(line))
    return "\n".join(lines)


def _strip_empty_headings(text: str) -> str:
    """Remove headings whose section contains no prose, table, list, or math.

    Fill models occasionally emit a grouping heading immediately followed by
    another heading at the same level (for example ``### 2 分类`` then
    ``### 2.1 第一类``).  The first line carries no learner-visible content and
    triggers the shared ``heading_with_empty_body`` delivery lint.  Removing
    only headings that satisfy the lint's exact empty-section definition keeps
    nested headings with real bodies intact.
    """

    lines = str(text or "").splitlines()
    headings: List[tuple[int, int]] = []
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match:
            headings.append((index, len(match.group(1))))

    empty: set[int] = set()
    for position, (line_no, level) in enumerate(headings):
        end = len(lines)
        for next_no, next_level in headings[position + 1:]:
            if next_level <= level:
                end = next_no
                break
        body = lines[line_no + 1:end]
        if all(not line.strip() or _HEADING_RE.match(line) for line in body):
            empty.add(line_no)
    return "\n".join(line for index, line in enumerate(lines) if index not in empty)


def assemble(
    backbone: str,
    sections: Dict[str, str],
    figures: Dict[Any, Dict[str, str]],
    references: List[Dict[str, str]],
) -> str:
    """Assemble the final markdown document.

    Raises AssemblyError when a placeholder has no matching fragment, or when any
    fragment carries a machine fallback note. A backbone without placeholders, and
    a document without figures or references, is legal. Each reference may carry
    an ``n`` field fixing its footnote number; missing numbers fall back to
    sequential numbering from 1.
    """
    _check_leak(backbone, fragment="backbone")
    for sec_id, body in sections.items():
        _check_leak(body, fragment=f"section:{sec_id}")

    missing: List[str] = []

    def _fill(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key in sections:
            return sections[key]
        missing.append(key)
        return match.group(0)

    def _fig(match: "re.Match[str]") -> str:
        num = match.group(1)
        fig = figures.get(int(num), figures.get(num))
        if fig is None:
            missing.append(f"fig:{num}")
            return match.group(0)
        return f"![{fig.get('caption', '')}]({fig.get('url', '')})"

    out = FILL_RE.sub(_fill, backbone)
    out = FIG_RE.sub(_fig, out)

    if missing:
        raise AssemblyError(
            ", ".join(missing),
            code="missing_fragments",
            missing=missing,
        )

    out = _strip_empty_headings(out)

    if references:
        lines = ["## 参考文献", ""]
        for idx, ref in enumerate(references, start=1):
            n = ref.get("n") or idx
            lines.append(f"[^{n}]: {ref.get('title', '')} — {ref.get('url', '')}")
        out = out.rstrip() + "\n\n" + "\n".join(lines) + "\n"

    return out.rstrip() + "\n\n---\n\n" + CLOSING_FOOTER + "\n"
