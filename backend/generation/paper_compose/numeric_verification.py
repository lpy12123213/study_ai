from __future__ import annotations

from typing import Any, Dict, List

from backend.core.logging_utils import get_logger
from backend.integrations.mcp.tools.python_scientific_compute import python_scientific_compute

logger = get_logger(__name__)

_NUMERIC_TYPE_TOKENS = ("计算", "解答", "简答", "综合", "calculation", "short_answer")
_VERIFICATION_CODE_KEYS = (
    "numeric_verification_code",
    "verification_code",
    "compute_check_code",
    "answer_check_code",
)


def _is_numeric_candidate(question: Dict[str, Any]) -> bool:
    text = " ".join(
        str(question.get(k) or "")
        for k in ("type", "question_type", "questionType", "category")
    ).strip().lower()
    return any(token.lower() in text for token in _NUMERIC_TYPE_TOKENS)


def _verification_code(question: Dict[str, Any]) -> str:
    for key in _VERIFICATION_CODE_KEYS:
        code = str(question.get(key) or "").strip()
        if code:
            return code
    return ""


def _append_quality_flag(question: Dict[str, Any], flag: str) -> None:
    raw = question.get("quality_flags")
    flags = list(raw) if isinstance(raw, list) else []
    if isinstance(raw, str) and raw.strip():
        flags.append(raw.strip())
    if flag not in flags:
        flags.append(flag)
    question["quality_flags"] = flags


def _mark_needs_human(question: Dict[str, Any], *, reason: str) -> None:
    if str(question.get("review_action") or "").strip().lower() != "reject":
        question["review_status"] = "needs_human"
        question["review_action"] = "needs_human"
    summary = str(question.get("review_summary") or "").strip()
    note = f"数值验算需人工复核：{reason}"
    question["review_summary"] = f"{summary}；{note}" if summary else note


def _result_is_true(result: Dict[str, Any]) -> bool:
    raw = str(result.get("result_repr") or result.get("stdout") or "").strip()
    normalized = raw.strip("'\"").strip().lower()
    return normalized in {"true", "1", "1.0", "yes", "ok"}


async def verify_numeric_answers(
    questions: List[Dict[str, Any]],
    *,
    enabled: bool = False,
    max_items: int = 20,
    timeout_seconds: int = 3,
) -> Dict[str, Any]:
    """Optionally run explicit numeric verification code for calculation-style questions.

    This wrapper never blocks paper generation on a failed check; it only annotates the
    question so export/review surfaces can ask a human to inspect it.
    """

    if not enabled:
        return {"enabled": False, "checked": 0, "passed": 0, "failed": 0, "skipped": 0, "items": []}

    try:
        limit = max(0, min(int(max_items or 0), 100))
    except (TypeError, ValueError):
        limit = 20
    try:
        timeout = max(1, min(int(timeout_seconds or 3), 15))
    except (TypeError, ValueError):
        timeout = 3

    checked = 0
    passed = 0
    failed = 0
    skipped = 0
    items: List[Dict[str, Any]] = []

    for question in questions or []:
        if not isinstance(question, dict):
            skipped += 1
            continue
        if not _is_numeric_candidate(question):
            skipped += 1
            continue
        if limit and checked >= limit:
            skipped += 1
            continue

        qid = str(question.get("question_id") or question.get("questionId") or "").strip()
        code = _verification_code(question)
        if not code:
            skipped += 1
            items.append({"question_id": qid, "status": "skipped", "reason": "missing_verification_code"})
            continue

        checked += 1
        try:
            result = await python_scientific_compute(
                code=code,
                purpose=f"paper_compose_numeric_verification:{qid or 'unknown'}",
                timeout_seconds=timeout,
            )
        except (RuntimeError, TypeError, ValueError, OSError) as exc:
            logger.warning("paper_compose_numeric_verification_failed", exc_info=True, extra={"question_id": qid})
            result = {"success": False, "error": str(exc)}

        question["numeric_verification"] = {
            "success": bool(result.get("success")),
            "passed": bool(result.get("success")) and _result_is_true(result),
            "result_repr": str(result.get("result_repr") or "").strip(),
            "error": str(result.get("error") or "").strip(),
        }

        if bool(result.get("success")) and _result_is_true(result):
            passed += 1
            items.append({"question_id": qid, "status": "passed"})
            continue

        failed += 1
        flag = "numeric_verification_failed" if bool(result.get("success")) else "numeric_verification_error"
        _append_quality_flag(question, flag)
        _mark_needs_human(question, reason=flag)
        items.append(
            {
                "question_id": qid,
                "status": "failed",
                "reason": flag,
                "result_repr": str(result.get("result_repr") or "").strip(),
                "error": str(result.get("error") or "").strip(),
            }
        )

    return {
        "enabled": True,
        "checked": checked,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "items": items[:20],
    }
