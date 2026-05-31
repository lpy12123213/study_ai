"""Text/tail formatting helpers and question rendering for the CLI.

Pure presentation helpers: tail clipping/wrapping for the live UI, tool-call
log formatting, and the rich panels/tables used to review generated questions.
"""

from __future__ import annotations

import json
import textwrap
from typing import Any, Dict, List

from .helpers import _rich_available


def _append_tail(existing: str, addition: str, *, max_lines: int = 120, max_chars: int = 12000) -> str:
    lines: List[str] = []
    if existing:
        lines.extend(str(existing).splitlines())
    if addition:
        lines.extend(str(addition).splitlines())
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    out = "\n".join(lines).rstrip()
    if max_chars > 0 and len(out) > max_chars:
        out = out[-max_chars:].lstrip()
    return out


def _tail_display(text: str, *, max_lines: int, width: int) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    width = max(20, int(width or 80))
    want_lines = max(6, int(max_lines or 30))

    wrapped: List[str] = []
    for ln in raw.split("\n"):
        if ln == "":
            wrapped.append("")
            continue
        wrapped.extend(
            textwrap.wrap(
                ln,
                width=width,
                break_long_words=True,
                replace_whitespace=False,
                drop_whitespace=False,
            )
        )

    if len(wrapped) > want_lines:
        wrapped = wrapped[-want_lines:]
        if wrapped:
            wrapped[0] = "… " + wrapped[0]

    return "\n".join(wrapped).rstrip()


def _clip_preview(value: Any, *, max_chars: int = 1200) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            text = repr(value)
    text = str(text or "").strip()
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _indent_block(text: str, *, prefix: str = "    ") -> str:
    raw = str(text or "").strip("\n")
    if not raw:
        return ""
    return "\n".join(prefix + line for line in raw.splitlines())


def _format_tool_call_log(tool_name: str, arguments: Dict[str, Any]) -> str:
    body = _clip_preview(arguments, max_chars=1600)
    return f"[tool_call] {tool_name}\n{_indent_block(body)}"


def _format_tool_result_log(tool_name: str, result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return f"[tool_result] {tool_name}\n{_indent_block(_clip_preview(result, max_chars=1200))}"

    summary: Dict[str, Any] = {}
    for key in (
        "success",
        "provider",
        "query",
        "mode",
        "purpose",
        "result_type",
        "result_repr",
        "stdout",
        "error",
        "detail",
    ):
        if key in result and result.get(key) not in (None, "", [], {}):
            summary[key] = result.get(key)
    if isinstance(result.get("results"), list):
        summary["results_count"] = len(result.get("results") or [])
    body = _clip_preview(summary or result, max_chars=1800)
    return f"[tool_result] {tool_name}\n{_indent_block(body)}"


def _render_question_panel(console, q: dict, *, index: int) -> None:  # noqa: ANN001
    if not _rich_available():
        print(
            f"[{index}] {q.get('question_id')}\n{q.get('stem')}\n答: {q.get('answer')}\n解: {q.get('analysis')}\n"
        )
        return

    from rich.markdown import Markdown
    from rich.panel import Panel

    stem = str(q.get("stem") or "").strip()
    answer = str(q.get("answer") or "").strip()
    analysis = str(q.get("analysis") or "").strip()
    review_status = str(q.get("review_status") or "").strip()
    difficulty = str(q.get("difficulty") or "").strip()
    judge_score = q.get("judge_score")
    score_text = ""
    if judge_score is not None:
        try:
            score_text = f" score={int(judge_score)}"
        except (TypeError, ValueError):
            score_text = f" score={judge_score}"
    diff_text = f" {difficulty}" if difficulty else ""
    title = f"{index}. {str(q.get('question_id') or '').strip()} [{review_status}]{diff_text}{score_text}"
    body_md = f"### 题干\n\n{stem}\n\n### 答案\n\n{answer}\n\n### 解析\n\n{analysis}\n"
    console.print(Panel(Markdown(body_md), title=title, border_style="green" if q.get("keep", True) else "red"))


def _render_questions_summary(console, drafts: List[dict]) -> None:  # noqa: ANN001
    if not _rich_available():
        for i, q in enumerate(drafts, start=1):
            print(i, q.get("question_id"), q.get("review_status"), "keep" if q.get("keep", True) else "drop")
        return

    from rich.table import Table

    table = Table(title="题目摘要", show_lines=False)
    table.add_column("#", justify="right")
    table.add_column("question_id")
    table.add_column("status")
    table.add_column("difficulty")
    table.add_column("score", justify="right")
    table.add_column("keep")
    table.add_column("stem_preview")
    for i, q in enumerate(drafts, start=1):
        stem = str(q.get("stem") or "").strip().replace("\n", " ")
        preview = stem[:60] + ("…" if len(stem) > 60 else "")
        table.add_row(
            str(i),
            str(q.get("question_id") or ""),
            str(q.get("review_status") or ""),
            str(q.get("difficulty") or ""),
            "" if q.get("judge_score") is None else str(q.get("judge_score")),
            "yes" if bool(q.get("keep", True)) else "no",
            preview,
        )
    console.print(table)
