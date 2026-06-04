from __future__ import annotations

from typing import Any, Dict, List

from backend.core.logging_utils import get_logger
from backend.generation.question_library.draft_realization import regenerate_question_section

logger = get_logger(__name__)


def _needs_synthesis(question: Dict[str, Any]) -> bool:
    stem = str((question or {}).get("stem") or "").strip()
    if not stem:
        return False
    return not str(question.get("answer") or "").strip() or not str(question.get("analysis") or "").strip()


async def synthesize_missing_answers(
    questions: List[Dict[str, Any]],
    *,
    subject: str,
    topic: str,
    max_items: int = 20,
) -> Dict[str, Any]:
    """Fill missing answer/analysis fields in-place for selected paper questions."""

    limit = max(0, min(int(max_items or 0), 100))
    updated = 0
    skipped = 0
    failed = 0
    items: List[Dict[str, Any]] = []

    for question in questions or []:
        if limit and updated >= limit:
            skipped += 1
            continue
        if not isinstance(question, dict) or not _needs_synthesis(question):
            skipped += 1
            continue

        qid = str(question.get("question_id") or "").strip()
        stem = str(question.get("stem") or "").strip()
        qtype = str(question.get("question_type") or question.get("type") or "").strip()
        difficulty = str(question.get("difficulty") or "").strip()
        before_answer = str(question.get("answer") or "").strip()
        before_analysis = str(question.get("analysis") or "").strip()

        try:
            if not before_answer:
                answer = await regenerate_question_section(
                    subject=subject,
                    topic=topic,
                    difficulty=difficulty,
                    question_type=qtype,
                    study_markdown="",
                    section_key="answer",
                    stem=stem,
                    answer=before_answer,
                    analysis=before_analysis,
                )
                if str(answer or "").strip():
                    question["answer"] = str(answer).strip()

            if not str(question.get("analysis") or "").strip():
                analysis = await regenerate_question_section(
                    subject=subject,
                    topic=topic,
                    difficulty=difficulty,
                    question_type=qtype,
                    study_markdown="",
                    section_key="analysis",
                    stem=stem,
                    answer=str(question.get("answer") or before_answer).strip(),
                    analysis=before_analysis,
                )
                if str(analysis or "").strip():
                    question["analysis"] = str(analysis).strip()
        except (RuntimeError, TypeError, ValueError):
            logger.warning("paper_compose_answer_synthesis_failed", exc_info=True, extra={"question_id": qid})
            failed += 1
            items.append({"question_id": qid, "status": "failed"})
            continue

        after_answer = str(question.get("answer") or "").strip()
        after_analysis = str(question.get("analysis") or "").strip()
        changed = (after_answer and after_answer != before_answer) or (after_analysis and after_analysis != before_analysis)
        if changed:
            question["answer_source"] = "ai_synthesis"
            updated += 1
            items.append({"question_id": qid, "status": "updated"})
        else:
            skipped += 1
            items.append({"question_id": qid, "status": "skipped"})

    return {"updated": updated, "skipped": skipped, "failed": failed, "items": items[:20]}
