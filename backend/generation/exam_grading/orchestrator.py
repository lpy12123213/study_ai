from __future__ import annotations

from typing import Any, Dict

from backend.database.repositories.exam import exam_sessions as exam_repo
from backend.generation.exam_grading.objective import grade_objective_answer, is_objective_question
from backend.generation.exam_grading.subjective import grade_subjective_answer


def _answer_for_question(answers: list[dict], question_id: str) -> dict:
    for answer in answers:
        if str(answer.get("question_id") or "").strip() == question_id:
            return answer
    return {}


async def grade_exam_session(*, user_id: str, session_id: str) -> Dict[str, Any]:
    """Grade an exam session, persist per-answer scores and create the final result."""

    session = await exam_repo.get_exam_session(user_id=user_id, session_id=session_id, include_answers=True)
    if not session:
        raise ValueError("session_not_found")
    if session.get("status") == "submitted" and session.get("result"):
        return dict(session["result"])

    answers = session.get("answers") or []
    total_score = 0.0
    max_score = 0.0
    objective_correct = 0
    objective_total = 0
    subjective_score = 0.0
    subjective_max = 0.0
    breakdown: list[dict] = []

    for question in session.get("questions") or []:
        if not isinstance(question, dict):
            continue
        qid = str(question.get("question_id") or "").strip()
        qtype = str(question.get("question_type") or question.get("type") or "").strip()
        answer = _answer_for_question(answers, qid)
        qmax = float(question.get("max_score") or answer.get("max_score") or 0.0)
        max_score += qmax

        if is_objective_question(qtype):
            objective_total += 1
            scored = grade_objective_answer(
                question_type=qtype,
                expected_answer=str(question.get("answer") or ""),
                answer_data=answer,
                max_score=qmax,
            )
            if scored.get("is_correct"):
                objective_correct += 1
        else:
            scored = await grade_subjective_answer(question=question, answer_data=answer, max_score=qmax)
            subjective_score += float(scored.get("score") or 0.0)
            subjective_max += qmax

        score = float(scored.get("score") or 0.0)
        total_score += score
        if answer.get("id"):
            await exam_repo.update_answer_score(
                user_id=user_id,
                answer_id=int(answer["id"]),
                score_data=scored,
            )

        breakdown.append(
            {
                "question_id": qid,
                "question_type": qtype,
                "score": score,
                "max_score": qmax,
                "is_correct": scored.get("is_correct"),
                "grading": scored.get("grading_json") or {},
            }
        )

    score_ratio = round(total_score / max_score, 4) if max_score > 0 else 0.0
    result_data = {
        "total_score": round(total_score, 2),
        "max_score": round(max_score, 2),
        "score_ratio": score_ratio,
        "objective_correct": objective_correct,
        "objective_total": objective_total,
        "subjective_score": round(subjective_score, 2),
        "subjective_max": round(subjective_max, 2),
        "breakdown": breakdown,
        "ai_feedback": {
            "summary": "已完成自动批改。",
            "score_ratio": score_ratio,
        },
    }
    await exam_repo.submit_session(
        user_id=user_id,
        session_id=session_id,
        total_score=float(result_data["total_score"]),
        max_score=float(result_data["max_score"]),
    )
    return await exam_repo.create_exam_result(user_id=user_id, session_id=session_id, result_data=result_data)
