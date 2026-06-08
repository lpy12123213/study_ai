"""Read-only browser for local question-bank items."""

from __future__ import annotations

import argparse
import asyncio
from typing import List, Optional

from backend.cli.common import _console, _prompt_text, _safe_user_id
from backend.cli.question_bank._ui import render_item_detail, render_items_table
from backend.database.repositories.question.question_cache import get_question_cache
from backend.database.repositories.question.question_library import list_question_library_items


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="浏览本地题库条目。")
    parser.add_argument("--user-id", default="1")
    parser.add_argument("--subject", default="")
    parser.add_argument("--origin", default="")
    parser.add_argument("--hidden", choices=["0", "1", "all"], default="0")
    parser.add_argument("--q", default="")
    parser.add_argument("--min-score", type=int, default=None)
    parser.add_argument("--sort", choices=["updated_at", "ai_score"], default="updated_at")
    parser.add_argument("--order", choices=["asc", "desc"], default="desc")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--page", type=int, default=1)
    return parser


async def _fetch_page(args: argparse.Namespace, *, page: int) -> dict:
    limit = max(1, min(int(args.limit or 20), 100))
    offset = max(0, int(page - 1) * limit)
    return await list_question_library_items(
        user_id=_safe_user_id(str(args.user_id or "")),
        subject=str(args.subject or "").strip(),
        origin=str(args.origin or "").strip(),
        hidden=str(args.hidden or "0"),
        q=str(args.q or "").strip(),
        min_score=args.min_score,
        sort=str(args.sort or "updated_at"),
        order=str(args.order or "desc"),
        limit=limit,
        offset=offset,
        include_total=True,
    )


async def _show_detail(console, item: dict) -> None:  # noqa: ANN001
    qid = str(item.get("question_id") or "").strip()
    cache = await get_question_cache(question_ids=[qid])
    render_item_detail(console, item, cache.get(qid, {}))


async def _run(args: argparse.Namespace) -> int:
    console = _console()
    page = max(1, int(args.page or 1))

    while True:
        result = await _fetch_page(args, page=page)
        items = list(result.get("items") or [])
        total = result.get("total")
        console.rule(f"题库浏览 page={page}" + (f" total={total}" if total is not None else ""))
        render_items_table(console, items)

        raw = _prompt_text("n下一页 / p上一页 / s检索 / f隐藏过滤 / 序号详情 / q退出", default="q")
        key = str(raw or "").strip().lower()
        if key in {"q", "quit", "exit"}:
            return 0
        if key == "n":
            if not items:
                continue
            page += 1
            continue
        if key == "p":
            page = max(1, page - 1)
            continue
        if key == "s":
            args.q = _prompt_text("检索关键词", default=str(args.q or ""))
            page = 1
            continue
        if key == "f":
            current = str(args.hidden or "0")
            args.hidden = {"0": "1", "1": "all", "all": "0"}.get(current, "0")
            page = 1
            continue
        try:
            idx = int(key)
        except ValueError:
            continue
        if 1 <= idx <= len(items):
            await _show_detail(console, items[idx - 1])


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))
