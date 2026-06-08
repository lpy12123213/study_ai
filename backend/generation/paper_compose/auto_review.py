from __future__ import annotations

from typing import Any, Dict, List

from backend.core.logging_utils import get_logger
from backend.generation.question_library.judging import check_ambiguity, judge_draft, solve_draft

logger = get_logger(__name__)


def _is_ai_question(question: Dict[str, Any]) -> bool:
    qid = str((question or {}).get("question_id") or "").strip().lower()
    source = str((question or {}).get("source") or "").strip().lower()
    return qid.startswith("ai_") or source.startswith("ai_") or "ai_generate" in source


def _has_llm_not_configured(result: Dict[str, Any]) -> bool:
    issues = result.get("issues") if isinstance(result, dict) else []
    return isinstance(issues, list) and any(str(x) == "llm_not_configured" for x in issues)


def _mark_needs_human(
    question: Dict[str, Any],
    *,
    qid: str,
    items: List[Dict[str, Any]],
    mode: str,
) -> None:
    question["review_status"] = "needs_human"
    question["review_action"] = "needs_human"
    items.append({"question_id": qid, "action": "needs_human", "mode": mode})


async def review_questions(
    questions: List[Dict[str, Any]],
    *,
    subject: str,
    topic: str,
    judge_pass_score: int = 65,
    run_llm: bool = True,
    review_bank_questions: bool = False,
    max_items: int = 20,
) -> Dict[str, Any]:
    """Review selected questions in-place and return a compact summary."""

    pass_score = max(0, min(int(judge_pass_score or 65), 100))
    limit = max(0, min(int(max_items or 0), 100))
    passed = 0
    failed = 0
    skipped = 0
    items: List[Dict[str, Any]] = []

    reviewed = 0
    for question in questions or []:
        if not isinstance(question, dict):
            skipped += 1
            continue
        if limit and reviewed >= limit:
            skipped += 1
            continue

        qid = str(question.get("question_id") or "").strip()
        stem = str(question.get("stem") or "").strip()
        answer = str(question.get("answer") or "").strip()
        analysis = str(question.get("analysis") or "").strip()
        is_ai = _is_ai_question(question)
        should_llm_review = bool(run_llm and (is_ai or review_bank_questions))

        if not stem:
            question["review_status"] = "rejected"
            question["review_action"] = "reject"
            failed += 1
            items.append({"question_id": qid, "action": "reject", "reason": "missing_stem"})
            continue

        if not answer or not analysis:
            question["review_status"] = "needs_answer"
            question["review_action"] = "regenerate_answer"
            failed += 1
            items.append({"question_id": qid, "action": "regenerate_answer", "reason": "missing_answer_or_analysis"})
            continue

        if not should_llm_review:
            question["review_status"] = "passed"
            question["review_action"] = "pass"
            passed += 1
            items.append({"question_id": qid, "action": "pass", "mode": "heuristic"})
            continue

        reviewed += 1
        try:
            solve_result = await solve_draft(
                stem,
                {"subject": subject, "topic": topic, "proposed_answer": answer},
            )
            if _has_llm_not_configured(solve_result):
                _mark_needs_human(question, qid=qid, items=items, mode="llm_not_configured")
                failed += 1
                continue
            if not bool(solve_result.get("match")):
                question["review_status"] = "needs_answer"
                question["review_action"] = "regenerate_answer"
                failed += 1
                items.append({"question_id": qid, "action": "regenerate_answer", "reason": "answer_mismatch"})
                continue

            ambiguity = await check_ambiguity(question)
            if _has_llm_not_configured(ambiguity):
                _mark_needs_human(question, qid=qid, items=items, mode="llm_not_configured")
                failed += 1
                continue
            if bool(ambiguity.get("ambiguous")):
                question["review_status"] = "rejected"
                question["review_action"] = "reject"
                failed += 1
                items.append({"question_id": qid, "action": "reject", "reason": "ambiguous"})
                continue

            judge = await judge_draft(
                question,
                {
                    "subject": subject,
                    "topic": topic,
                    "difficulty": str(question.get("difficulty") or ""),
                    "question_type": str(question.get("question_type") or question.get("type") or ""),
                },
                source_pack={"subject": subject, "topic": topic},
            )
            if _has_llm_not_configured(judge):
                _mark_needs_human(question, qid=qid, items=items, mode="llm_not_configured")
                failed += 1
                continue

            try:
                score = int(judge.get("overall_score") or 0)
            except (TypeError, ValueError):
                score = 0
            question["review_score"] = score
            question["review_summary"] = str(judge.get("summary") or "").strip()
            if bool(judge.get("pass")) and score >= pass_score:
                question["review_status"] = "passed"
                question["review_action"] = "pass"
                passed += 1
                items.append({"question_id": qid, "action": "pass", "score": score})
            else:
                question["review_status"] = "rejected"
                question["review_action"] = "reject"
                failed += 1
                items.append({"question_id": qid, "action": "reject", "score": score})
        except (RuntimeError, TypeError, ValueError):
            logger.warning("paper_compose_auto_review_question_failed", exc_info=True, extra={"question_id": qid})
            _mark_needs_human(question, qid=qid, items=items, mode="review_error")
            failed += 1

    return {"passed": passed, "failed": failed, "skipped": skipped, "replaced": 0, "items": items[:20]}
