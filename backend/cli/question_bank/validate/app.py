"""Quality validation for local question-bank items."""

from __future__ import annotations

import argparse
import asyncio
import re
from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional

from backend.cli.common import _console, _prompt_bool, _rich_available, _safe_user_id
from backend.database.repositories.question.question_cache import get_question_cache
from backend.database.repositories.question.question_library import (
    list_question_library_items,
    set_hidden,
    upsert_question_library_items,
)


@dataclass(frozen=True)
class ValidationIssue:
    question_id: str
    code: str
    detail: str


_BAD_MARKUP_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("formula_placeholder", re.compile(r"\[公式:[^\]]+\]")),
    ("image_placeholder", re.compile(r"\[图片:[^\]]+\]")),
    ("raw_inline_latex_delimiter", re.compile(r"\\[()]")),
    ("raw_block_latex_delimiter", re.compile(r"\\[\[\]]")),
]


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def detect_bad_markup(text: str) -> list[str]:
    raw = str(text or "")
    hits: list[str] = []
    for name, pattern in _BAD_MARKUP_PATTERNS:
        if pattern.search(raw):
            hits.append(name)
    return hits


def _non_empty_quality_flags(value: Any) -> str:
    raw = str(value or "").strip()
    if raw in {"", "[]", "{}"}:
        return ""
    return raw


def detect_item_issues(
    item: Mapping[str, Any],
    cache_row: Mapping[str, Any] | None = None,
    *,
    min_quality: int = 0,
) -> list[ValidationIssue]:
    cache = cache_row or {}
    qid = str(item.get("question_id") or cache.get("question_id") or "").strip()
    issues: list[ValidationIssue] = []

    if not (_has_text(cache.get("answer")) or bool(item.get("has_answer"))):
        issues.append(ValidationIssue(qid, "missing_answer", "answer is empty"))

    if not (_has_text(cache.get("analysis")) or bool(item.get("has_analysis"))):
        issues.append(ValidationIssue(qid, "missing_analysis", "analysis is empty"))

    quality_score = _as_int(cache.get("quality_score", item.get("quality_score")), 0)
    threshold = _as_int(min_quality, 0)
    if threshold > 0 and quality_score < threshold:
        issues.append(ValidationIssue(qid, "low_quality", f"quality_score={quality_score} < {threshold}"))

    quality_flags = _non_empty_quality_flags(cache.get("quality_flags"))
    if quality_flags:
        issues.append(ValidationIssue(qid, "quality_flags", quality_flags))

    markup_hits = detect_bad_markup(str(cache.get("stem") or item.get("stem") or ""))
    if markup_hits:
        issues.append(ValidationIssue(qid, "bad_markup", ",".join(markup_hits)))

    return issues


def collect_validation_issues(
    items: Iterable[Mapping[str, Any]],
    cache_by_id: Mapping[str, Mapping[str, Any]],
    *,
    min_quality: int,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for item in items:
        qid = str(item.get("question_id") or "").strip()
        issues.extend(detect_item_issues(item, cache_by_id.get(qid, {}), min_quality=min_quality))
    return issues


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="校验本地题库质量，默认只读。")
    parser.add_argument("--user-id", default="1")
    parser.add_argument("--subject", default="")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--min-quality", type=int, default=0)
    parser.add_argument("--fix", action="store_true", help="二次确认后写入修复动作")
    parser.add_argument("--fix-action", choices=["hide", "flag"], default="hide")
    return parser


async def _load_items(*, user_id: str, subject: str, limit: int) -> list[dict]:
    want = max(1, int(limit or 200))
    out: list[dict] = []
    offset = 0
    while len(out) < want:
        page_limit = min(200, want - len(out))
        page = await list_question_library_items(
            user_id=user_id,
            subject=subject,
            hidden="all",
            limit=page_limit,
            offset=offset,
            include_total=False,
        )
        items = list(page.get("items") or [])
        if not items:
            break
        out.extend(items)
        offset += len(items)
        if len(items) < page_limit:
            break
    return out


def _render_issues(console, issues: list[ValidationIssue]) -> None:  # noqa: ANN001
    if not issues:
        console.print("未发现质量问题。")
        return

    if not _rich_available():
        for issue in issues:
            console.print(f"{issue.question_id}\t{issue.code}\t{issue.detail}")
        console.print(f"共 {len(issues)} 条问题。")
        return

    from rich.table import Table

    table = Table(title="题库质量校验", show_lines=False)
    table.add_column("qid", no_wrap=True)
    table.add_column("问题", no_wrap=True)
    table.add_column("详情")
    for issue in issues:
        table.add_row(issue.question_id, issue.code, issue.detail)
    console.print(table)
    console.print(f"共 {len(issues)} 条问题，涉及 {len({x.question_id for x in issues})} 道题。")


async def _apply_fix(*, user_id: str, issues: list[ValidationIssue], action: str) -> int:
    question_ids = list(dict.fromkeys(issue.question_id for issue in issues if issue.question_id))
    if not question_ids:
        return 0

    if action == "hide":
        n = 0
        for qid in question_ids:
            if await set_hidden(user_id=user_id, question_id=qid, hidden=True):
                n += 1
        return n

    items = [
        {
            "question_id": qid,
            "ai_verdict": "needs_fix",
            "ai_summary": "question_bank_validate",
        }
        for qid in question_ids
    ]
    return await upsert_question_library_items(user_id=user_id, items=items)


async def _run(args: argparse.Namespace) -> int:
    uid = _safe_user_id(str(args.user_id or ""))
    items = await _load_items(user_id=uid, subject=str(args.subject or "").strip(), limit=int(args.limit or 200))
    cache_by_id = await get_question_cache(question_ids=[str(x.get("question_id") or "") for x in items])
    issues = collect_validation_issues(items, cache_by_id, min_quality=int(args.min_quality or 0))

    console = _console()
    _render_issues(console, issues)

    if not args.fix or not issues:
        return 0

    action = str(args.fix_action or "hide")
    if not _prompt_bool(f"确认对 {len({x.question_id for x in issues})} 道题执行 {action}", default=False):
        console.print("已取消写入。")
        return 0

    changed = await _apply_fix(user_id=uid, issues=issues, action=action)
    console.print(f"已写入 {changed} 道题。")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))
