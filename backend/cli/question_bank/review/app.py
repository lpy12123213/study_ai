"""Interactive review queue for local crawled question-bank items."""

from __future__ import annotations

import argparse
import asyncio
from typing import List, Optional

from backend.cli.common import _console, _prompt_text, _safe_user_id
from backend.cli.question_bank._ui import render_item_detail
from backend.database.repositories.question.question_cache import get_question_cache
from backend.database.repositories.question.question_library import (
    list_unscored_question_ids,
    set_hidden,
    set_starred,
    upsert_question_library_items,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="审核待评分的爬取题，并可收藏、隐藏或评分。")
    parser.add_argument("--user-id", default="1")
    parser.add_argument("--subject", default="")
    parser.add_argument("--limit", type=int, default=50)
    return parser


async def _load_queue(*, user_id: str, subject: str, limit: int) -> tuple[list[str], dict[str, dict]]:
    ids = await list_unscored_question_ids(user_id=user_id, subject=subject, limit=limit)
    cache = await get_question_cache(question_ids=ids)
    return ids, cache


async def _apply_action(*, user_id: str, qid: str, action: str) -> str:
    if action == "s":
        ok = await set_starred(user_id=user_id, question_id=qid, starred=True)
        return "已收藏" if ok else "收藏失败"
    if action == "h":
        ok = await set_hidden(user_id=user_id, question_id=qid, hidden=True)
        return "已隐藏" if ok else "隐藏失败"
    if action in {"1", "2", "3", "4", "5"}:
        await upsert_question_library_items(
            user_id=user_id,
            items=[
                {
                    "question_id": qid,
                    "ai_score": int(action),
                    "ai_verdict": f"review_score_{action}",
                }
            ],
        )
        return f"已评分 {action}"
    return ""


async def _run(args: argparse.Namespace) -> int:
    uid = _safe_user_id(str(args.user_id or ""))
    subject = str(args.subject or "").strip()
    limit = max(1, min(int(args.limit or 50), 500))
    ids, cache_by_id = await _load_queue(user_id=uid, subject=subject, limit=limit)
    console = _console()

    if not ids:
        console.print("没有待复核的题目。")
        return 0

    idx = 0
    while 0 <= idx < len(ids):
        qid = ids[idx]
        item = {
            "question_id": qid,
            "subject": cache_by_id.get(qid, {}).get("subject") or subject,
            "question_type": cache_by_id.get(qid, {}).get("question_type") or "",
        }
        console.rule(f"待审 {idx + 1}/{len(ids)}")
        render_item_detail(console, item, cache_by_id.get(qid, {}))
        raw = _prompt_text("s收藏 / h隐藏 / 1-5评分 / n下一题 / b上一题 / q退出", default="n")
        action = str(raw or "").strip().lower()
        if action in {"q", "quit", "exit"}:
            return 0
        if action == "b":
            idx = max(0, idx - 1)
            continue
        if action == "n":
            idx += 1
            continue

        message = await _apply_action(user_id=uid, qid=qid, action=action)
        if message:
            console.print(message)
            idx += 1

    console.print("审核队列已结束。")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))
