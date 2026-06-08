"""Stats and duplicate grouping for local question-bank items."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional

from backend.cli.common import _console, _rich_available, _safe_user_id
from backend.database.repositories.question.question_cache import get_question_cache
from backend.database.repositories.question.question_library import (
    list_question_library_items,
    list_thinking_method_stats,
)
from backend.database.repositories.system.search import search_fulltext


def _as_score_bucket(value: Any) -> str:
    if value is None:
        return "未评分"
    try:
        score = int(value)
    except (TypeError, ValueError):
        return "未知"
    if score < 60:
        return "<60"
    if score < 80:
        return "60-79"
    if score < 90:
        return "80-89"
    return "90+"


def build_distribution(items: Iterable[Mapping[str, Any]]) -> dict[str, Counter[str]]:
    dist: dict[str, Counter[str]] = {
        "subject": Counter(),
        "origin": Counter(),
        "score": Counter(),
        "hidden": Counter(),
        "starred": Counter(),
    }
    for item in items:
        dist["subject"][str(item.get("subject") or "未填")] += 1
        dist["origin"][str(item.get("origin") or "未知")] += 1
        dist["score"][_as_score_bucket(item.get("ai_score"))] += 1
        dist["hidden"]["隐藏" if item.get("hidden") else "可见"] += 1
        dist["starred"]["收藏" if item.get("starred") else "未收藏"] += 1
    return dist


def find_duplicate_stem_groups(rows: Iterable[Mapping[str, Any]]) -> list[dict]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        fp = str(row.get("stem_fingerprint") or "").strip()
        qid = str(row.get("question_id") or "").strip()
        if not fp or not qid:
            continue
        grouped[fp].append(row)

    out: list[dict] = []
    for fp, members in grouped.items():
        if len(members) < 2:
            continue
        out.append(
            {
                "stem_fingerprint": fp,
                "count": len(members),
                "question_ids": [str(x.get("question_id") or "").strip() for x in members],
                "items": list(members),
            }
        )
    out.sort(key=lambda g: (-int(g.get("count") or 0), str(g.get("stem_fingerprint") or "")))
    return out


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="统计本地题库分布，并可按题干指纹发现重复题。")
    parser.add_argument("--user-id", default="1")
    parser.add_argument("--subject", default="")
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--dedup", action="store_true")
    parser.add_argument("--query", default="", help="在全文索引中查找相近的已存内容")
    return parser


async def _load_items(*, user_id: str, subject: str, limit: int) -> list[dict]:
    want = max(1, int(limit or 2000))
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


def _render_counter(console, title: str, counter: Counter[str]) -> None:  # noqa: ANN001
    if not _rich_available():
        console.print(f"\n{title}")
        for key, count in counter.most_common():
            console.print(f"  {key}: {count}")
        return

    from rich.table import Table

    table = Table(title=title, show_lines=False)
    table.add_column("项")
    table.add_column("数量", justify="right")
    for key, count in counter.most_common():
        table.add_row(str(key), str(count))
    console.print(table)


def _render_duplicates(console, groups: list[dict]) -> None:  # noqa: ANN001
    if not groups:
        console.print("未发现重复题干指纹。")
        return

    if not _rich_available():
        for group in groups:
            console.print(f"{group['stem_fingerprint']}\t{group['count']}\t{', '.join(group['question_ids'])}")
        return

    from rich.table import Table

    table = Table(title="重复题干指纹", show_lines=False)
    table.add_column("fingerprint", no_wrap=True)
    table.add_column("数量", justify="right", no_wrap=True)
    table.add_column("question_ids")
    for group in groups:
        table.add_row(group["stem_fingerprint"], str(group["count"]), ", ".join(group["question_ids"]))
    console.print(table)


async def _run(args: argparse.Namespace) -> int:
    uid = _safe_user_id(str(args.user_id or ""))
    subject = str(args.subject or "").strip()
    items = await _load_items(user_id=uid, subject=subject, limit=int(args.limit or 2000))
    console = _console()

    console.print(f"共载入 {len(items)} 道题。")
    dist = build_distribution(items)
    for title, counter in (
        ("按学科", dist["subject"]),
        ("按来源", dist["origin"]),
        ("按评分", dist["score"]),
        ("按隐藏", dist["hidden"]),
        ("按收藏", dist["starred"]),
    ):
        _render_counter(console, title, counter)

    method_stats = await list_thinking_method_stats(user_id=uid, subject=subject, limit=int(args.limit or 2000))
    if method_stats:
        _render_counter(
            console,
            "按思维方法",
            Counter({str(x.get("method_family") or ""): int(x.get("count") or 0) for x in method_stats}),
        )

    if args.dedup:
        cache_by_id = await get_question_cache(question_ids=[str(x.get("question_id") or "") for x in items])
        enriched: list[dict] = []
        for item in items:
            qid = str(item.get("question_id") or "").strip()
            row = dict(item)
            row.update(cache_by_id.get(qid, {}))
            enriched.append(row)
        _render_duplicates(console, find_duplicate_stem_groups(enriched))

    query = str(args.query or "").strip()
    if query:
        hits = await search_fulltext(user_id=uid, query=query, types=["paper", "question"], limit=10)
        console.print(f"全文索引命中 {len(hits)} 条。")
        for hit in hits[:10]:
            console.print(f"  {hit.get('type')} {hit.get('question_id') or hit.get('paper_id')}: {hit.get('title')}")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))
