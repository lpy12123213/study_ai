from __future__ import annotations

import asyncio
import os

from backend.llm.client import is_llm_configured
from backend.core.logging_utils import get_logger
from backend.core.settings import LESSON_PLAN_MODEL
from backend.database.repositories.question.question_cache import get_question_cache
from backend.database.repositories.question.question_library import list_unscored_question_ids
from backend.question_library.scoring import apply_score_and_hide, score_stem_with_llm

logger = get_logger(__name__)


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on"}


def _as_int(value: str, default: int) -> int:
    try:
        return int(str(value or "").strip())
    except Exception:
        return int(default)


async def score_batch_once(*, user_id: str, subject: str, model: str, threshold: int, limit: int) -> int:
    qids = await list_unscored_question_ids(user_id=user_id, subject=subject, limit=limit)
    if not qids:
        return 0
    cache = await get_question_cache(question_ids=qids)
    scored = 0
    for qid in qids:
        stem = str((cache.get(qid) or {}).get("stem") or "").strip()
        if not stem:
            continue
        res = await score_stem_with_llm(subject=subject, stem=stem, model=model)
        await apply_score_and_hide(
            user_id=user_id,
            question_id=qid,
            overall_score=int(res.get("overall_score") or 0),
            verdict=str(res.get("verdict") or ""),
            dimensions=list(res.get("dimensions") or []),
            summary=str(res.get("summary") or ""),
            threshold=threshold,
        )
        scored += 1
    return scored


async def run_question_library_scoring_worker(*, stop: asyncio.Event) -> None:
    if not _env_truthy("QUESTION_LIBRARY_AUTO_SCORE", default=False):
        return
    if not is_llm_configured():
        return

    interval_s = float(os.getenv("QUESTION_LIBRARY_SCORE_INTERVAL_S") or "20")
    threshold = _as_int(os.getenv("QUESTION_LIBRARY_HIDE_THRESHOLD") or "70", 70)
    batch = _as_int(os.getenv("QUESTION_LIBRARY_SCORE_BATCH") or "20", 20)
    user_id = str(os.getenv("QUESTION_LIBRARY_SCORE_USER_ID") or "1").strip() or "1"
    subject = str(os.getenv("QUESTION_LIBRARY_SCORE_SUBJECT") or "").strip()
    model = str(os.getenv("QUESTION_LIBRARY_SCORE_MODEL") or LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini"

    while not stop.is_set():
        try:
            await score_batch_once(
                user_id=user_id,
                subject=subject,
                model=model,
                threshold=threshold,
                limit=batch,
            )
        except Exception:
            logger.exception("question_library_worker_score_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(1.0, interval_s))
        except asyncio.TimeoutError:
            continue
