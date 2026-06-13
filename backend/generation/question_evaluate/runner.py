from __future__ import annotations

from typing import Any, Dict, List

from backend.api.question_evaluate_schemas import QuestionInput
from backend.core.settings import DEFAULT_SUBJECT, LESSON_PLAN_MODEL
from backend.core.subjects import resolve_subject
from backend.generation.agentic.codex_runtime import (
    is_codex_runtime_agent_runtime,
    legacy_agent_fallback_enabled,
    run_codex_runtime_task,
)
from backend.generation.question_evaluate.service import evaluate_questions_batch
from backend.shared.tasks import task_runtime
from backend.shared.tasks.runtime import RuntimeTask


def _question_from_payload(raw: Any) -> QuestionInput:
    if isinstance(raw, QuestionInput):
        return raw
    if isinstance(raw, dict):
        return QuestionInput(**raw)
    return QuestionInput()


async def run_question_evaluate_task(task: RuntimeTask, *, user_id: str) -> None:
    if is_codex_runtime_agent_runtime():
        handled = await run_codex_runtime_task(task, user_id=user_id, task_type="question_evaluate", final_event_type="done")
        if handled or not legacy_agent_fallback_enabled():
            return

    req = dict(task.request or {})
    raw_questions = req.get("questions") if isinstance(req.get("questions"), list) else []
    questions: List[QuestionInput] = [_question_from_payload(item) for item in raw_questions[:50]]
    questions = [q for q in questions if (q.question_id or q.stem or "").strip()]
    if not questions:
        raise RuntimeError("missing_questions")

    subject_input = str(req.get("subject") or DEFAULT_SUBJECT).strip()
    subject = resolve_subject(subject_input, strict=True)
    model = str(req.get("model") or "").strip() or str(LESSON_PLAN_MODEL or "").strip()
    if not model:
        raise RuntimeError("llm_model_not_configured")

    requirements = str(req.get("requirements") or "").strip()
    total = len(questions)

    await task_runtime.append_event(
        task,
        {
            "type": "progress",
            "data": {
                "progress": 3,
                "stage": "Validate",
                "completed": 0,
                "total": total,
            },
        },
    )

    async def on_progress(completed: int, total_count: int, _result: Any) -> None:
        progress = 5 + int((completed / max(1, total_count)) * 90)
        await task_runtime.append_event(
            task,
            {
                "type": "progress",
                "data": {
                    "progress": min(95, progress),
                    "stage": "Evaluate",
                    "completed": completed,
                    "total": total_count,
                },
            },
        )

    results = await evaluate_questions_batch(
        questions=questions,
        subject=subject,
        requirements=requirements,
        model=model,
        on_progress=on_progress,
    )
    failed_count = total - len(results)
    result_payload: Dict[str, Any] = {
        "success": failed_count == 0,
        "results": [item.model_dump() for item in results],
        "model": model,
        "count": len(results),
        "total": total,
        "failed_count": failed_count,
    }
    task.meta["result"] = result_payload

    await task_runtime.append_event(task, {"type": "done", "data": result_payload})
    await task_runtime.complete_task(task, result=result_payload)
