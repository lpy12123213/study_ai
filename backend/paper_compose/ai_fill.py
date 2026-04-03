from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.crawler.manager import get_crawler
from backend.question_library.generation import generate_questions
from backend.question_library.gen_utils import ReasoningEventHandler, build_ai_question_id

logger = get_logger(__name__)


def _stable_suffix(*, slot_index: int, index: int, salt: str) -> str:
    raw = f"{slot_index}:{index}:{salt}".encode("utf-8", errors="ignore")
    h = hashlib.sha1(raw).hexdigest()[:8]
    return h


async def fill_slot_with_ai(
    *,
    source_pack: dict,
    subject: str,
    topic: str,
    slot: dict,
    user_id: str,
    slot_index: int = 0,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
    fallback_to_crawler: bool = True,
) -> List[dict]:
    """Fill a single slot using AI question generation.

    Returns q_dicts compatible with `save_paper()` / `upsert_question_cache()`:
      {question_id, subject, type, difficulty, knowledge_point, stem, answer, analysis, source_url, ...}
    """

    sp = source_pack if isinstance(source_pack, dict) else {}
    subj = str(subject or sp.get("subject") or "").strip() or "高中数学"
    top = str(topic or sp.get("topic") or "").strip()
    slot_obj = slot if isinstance(slot, dict) else {}

    qtype = str(slot_obj.get("question_type") or slot_obj.get("type") or "").strip() or "解答题"
    try:
        count = int(slot_obj.get("count") or 0)
    except Exception:
        count = 0
    count = max(1, min(count, 30))
    difficulty = str(slot_obj.get("difficulty") or "").strip() or "中等"

    drafts: List[dict] = []
    try:
        drafts = await generate_questions(
            source_pack={**sp, "subject": subj, "topic": top},
            count=count,
            difficulty=difficulty,
            question_type=qtype,
            user_id=str(user_id or "").strip(),
            stream_reasoning=stream_reasoning,
            on_reasoning_event=on_reasoning_event,
            on_stage_event=None,
            config=None,
        )
    except Exception:
        drafts = []

    out: List[dict] = []
    for i, d in enumerate(drafts or []):
        if not isinstance(d, dict):
            continue
        stem = str(d.get("stem") or "").strip()
        answer = str(d.get("answer") or "").strip()
        analysis = str(d.get("analysis") or "").strip()
        if not stem or not answer or not analysis:
            continue

        suffix = _stable_suffix(slot_index=slot_index, index=i, salt=stem[:200])
        qid = str(d.get("question_id") or "").strip() or build_ai_question_id(suffix=suffix)
        item = {
            "question_id": qid,
            "subject": subj,
            "type": qtype,
            "question_type": qtype,
            "difficulty": difficulty,
            "knowledge_point": top,
            "source_url": "",
            "source": "ai_generate_full",
            "stem": stem,
            "answer": answer,
            "analysis": analysis,
        }
        # Optional diagram payload for downstream export/UI.
        diagrams = d.get("diagrams")
        if isinstance(diagrams, list):
            item["diagrams"] = [x for x in diagrams if isinstance(x, dict)][:6]

        out.append(item)
        if len(out) >= count:
            break

    if out:
        return out[:count]

    if not fallback_to_crawler:
        return []

    # Fallback: try crawler-based retrieval (best-effort).
    try:
        crawler = await get_crawler(subject=subj, edu_level="", strict=True)
        keyword = str(slot_obj.get("keyword") or top or "").strip() or "相关知识点"
        result = await crawler.search_by_keyword(
            keyword=keyword,
            subject=subj,
            edu_level="",
            limit=max(5, min(40, count * 6)),
            difficulty=difficulty,
            question_type=qtype,
            max_pages=2,
            dedup_by_stem=True,
            min_quality_score=0,
            with_quality=True,
            require_difficulty=False,
            strict_subject=True,
        )
        raw_qs = result.get("questions") if isinstance(result, dict) else None
        if not isinstance(raw_qs, list):
            return []
        for q in raw_qs:
            if not isinstance(q, dict):
                continue
            qid = str(q.get("question_id") or "").strip()
            if not qid:
                continue
            out.append(
                {
                    "question_id": qid,
                    "subject": subj,
                    "type": str(q.get("type") or qtype).strip() or qtype,
                    "difficulty": str(q.get("difficulty") or difficulty).strip() or difficulty,
                    "knowledge_point": top,
                    "source_url": str(q.get("source_url") or "").strip(),
                    "source": str(q.get("source") or "crawler").strip(),
                    "stem": str(q.get("stem") or "").strip(),
                    "answer": str(q.get("answer") or "").strip(),
                    "analysis": str(q.get("analysis") or "").strip(),
                }
            )
            if len(out) >= count:
                break
    except Exception:
        logger.debug("fill_slot_fallback_crawler_failed", exc_info=True, extra={"subject": subj})
        return []

    return out[:count]

