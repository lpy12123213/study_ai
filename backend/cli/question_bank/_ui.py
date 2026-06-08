"""Presentation helpers for local question-bank maintenance tools."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from backend.cli.common import _rich_available


def _text(value: Any) -> str:
    return str(value or "").strip()


def _score_text(value: Any) -> str:
    return "" if value is None else str(value)


def _preview(value: Any, *, max_chars: int = 80) -> str:
    text = _text(value).replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def render_items_table(console, items: Iterable[Mapping[str, Any]]) -> None:  # noqa: ANN001
    rows = list(items or [])
    if not rows:
        console.print("题库为空。")
        return

    if not _rich_available():
        for i, item in enumerate(rows, start=1):
            console.print(
                f"{i}. {item.get('question_id')} "
                f"{item.get('subject') or '-'} {item.get('question_type') or '-'} "
                f"score={_score_text(item.get('ai_score')) or '-'} "
                f"ans={'Y' if item.get('has_answer') else 'N'} "
                f"ana={'Y' if item.get('has_analysis') else 'N'} "
                f"{_preview(item.get('stem'))}"
            )
        return

    from rich.table import Table

    table = Table(title="本地题库", show_lines=False)
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("qid", no_wrap=True)
    table.add_column("学科", no_wrap=True)
    table.add_column("类型", no_wrap=True)
    table.add_column("分数", justify="right", no_wrap=True)
    table.add_column("★", justify="center", no_wrap=True)
    table.add_column("隐", justify="center", no_wrap=True)
    table.add_column("ans", justify="center", no_wrap=True)
    table.add_column("ana", justify="center", no_wrap=True)
    table.add_column("题干")

    for i, item in enumerate(rows, start=1):
        table.add_row(
            str(i),
            _text(item.get("question_id")),
            _text(item.get("subject")),
            _text(item.get("question_type")),
            _score_text(item.get("ai_score")),
            "Y" if item.get("starred") else "",
            "Y" if item.get("hidden") else "",
            "Y" if item.get("has_answer") else "N",
            "Y" if item.get("has_analysis") else "N",
            _preview(item.get("stem"), max_chars=96),
        )
    console.print(table)


def render_item_detail(console, item: Mapping[str, Any], cache_row: Mapping[str, Any] | None = None) -> None:  # noqa: ANN001
    cache = cache_row or {}
    qid = _text(item.get("question_id") or cache.get("question_id"))
    stem = _text(cache.get("stem") or item.get("stem"))
    answer = _text(cache.get("answer"))
    analysis = _text(cache.get("analysis"))
    verdict = _text(item.get("ai_verdict"))
    title = f"{qid} {item.get('subject') or ''} {item.get('question_type') or ''}".strip()

    if not _rich_available():
        console.print(f"\n[{title}]\n题干: {stem}\n答案: {answer}\n解析: {analysis}\n评价: {verdict}\n")
        return

    from rich.markdown import Markdown
    from rich.panel import Panel

    body_md = f"### 题干\n\n{stem or '题面不可用'}\n\n### 答案\n\n{answer or '-'}\n\n### 解析\n\n{analysis or '-'}\n"
    if verdict:
        body_md += f"\n### 评价\n\n{verdict}\n"
    console.print(Panel(Markdown(body_md), title=title or "题目详情", border_style="cyan"))
