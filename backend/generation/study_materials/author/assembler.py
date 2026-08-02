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

FILL_RE = re.compile(r"\[\[FILL:([A-Za-z0-9\-]+)\]\]")
FIG_RE = re.compile(r"\[\[FIG:(\d+)\]\]")
_FALLBACK_LEAK_RE = re.compile(r"未成功使用模型生成|兜底内容|source=llm_|退回到摘要")

# 收尾行：以句读终止符结束，消除 eof_mid_sentence lint（不用斜体标记，避免末尾 * 被判定截断）。
CLOSING_FOOTER = "本资料由作者代理生成，仅供学习参考。"


class AssemblyError(ValueError):
    """Raised when the backbone cannot be assembled into the final document."""


def _check_leak(text: str) -> None:
    if _FALLBACK_LEAK_RE.search(text):
        raise AssemblyError("fallback note leaked into content")


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
    _check_leak(backbone)
    for body in sections.values():
        _check_leak(body)

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
        raise AssemblyError(", ".join(missing))

    if references:
        lines = ["## 参考文献", ""]
        for idx, ref in enumerate(references, start=1):
            n = ref.get("n") or idx
            lines.append(f"[^{n}]: {ref.get('title', '')} — {ref.get('url', '')}")
        out = out.rstrip() + "\n\n" + "\n".join(lines) + "\n"

    return out.rstrip() + "\n\n---\n\n" + CLOSING_FOOTER + "\n"
