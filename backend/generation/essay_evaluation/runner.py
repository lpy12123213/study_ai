"""TaskRuntime runner for essay evaluation.

Bridges the synchronous :func:`evaluate_essay` service into the long-task
infrastructure (SSE progress, DB persistence, history list).
"""

from __future__ import annotations

from typing import Any, Dict

from backend.core.logging_utils import get_logger
from backend.database.repositories.generation.essay_evaluations import insert_evaluation
from backend.generation.essay_evaluation.essay_schemas import EssayEvaluationRequest
from backend.generation.essay_evaluation.service import evaluate_essay
from backend.shared.tasks import task_runtime
from backend.shared.tasks.runtime import RuntimeTask

logger = get_logger(__name__)


_STAGE_LABELS = {
    "parse": "解析作文",
    "prompt": "构建评分提示",
    "llm": "AI 评分中",
    "parse_response": "整理评分结果",
    "done": "完成",
}


async def run_essay_evaluation_task(task: RuntimeTask, *, user_id: str) -> None:
    req = dict(task.request or {})
    request = EssayEvaluationRequest(**req)

    async def on_progress(percent: int, stage: str) -> None:
        await task_runtime.append_event(
            task,
            {
                "type": "progress",
                "data": {
                    "progress": int(percent),
                    "stage": _STAGE_LABELS.get(stage, stage),
                    "stage_id": stage,
                },
            },
        )

    try:
        result = await evaluate_essay(request, on_progress=on_progress)
    except ValueError as exc:
        await task_runtime.fail_task(task, str(exc), error={"message": str(exc)})
        return
    except Exception as exc:  # pragma: no cover (logged for ops)
        logger.exception("essay_evaluation_task_failed", extra={"task_id": task.task_id, "user_id": user_id})
        await task_runtime.fail_task(task, str(exc) or "evaluation_failed", error={"message": str(exc)})
        return

    feedback_payload: Dict[str, Any] = {
        "summary": result.summary,
        "strengths": list(result.strengths),
        "weaknesses": list(result.weaknesses),
        "suggestions": list(result.suggestions),
        "paragraph_feedback": [item.model_dump() for item in result.paragraph_feedback],
        "rewrite": result.rewrite,
    }

    record = await insert_evaluation(
        user_id=user_id,
        essay_text=request.text,
        subject=request.subject,
        topic=request.topic,
        essay_type=request.essay_type,
        grade_band=request.grade_band,
        language=result.language,
        requirements=request.requirements,
        score_total=result.score_total,
        score_max=result.score_max,
        grade=result.grade,
        scores=[s.model_dump() for s in result.scores],
        feedback=feedback_payload,
        model=result.model,
    )

    payload: Dict[str, Any] = {
        "success": True,
        "evaluation_id": int(record.get("id") or 0),
        "result": result.model_dump(),
    }
    task.meta["result"] = payload

    await task_runtime.append_event(task, {"type": "done", "data": payload})
    await task_runtime.complete_task(task, result=payload)


__all__ = ["run_essay_evaluation_task"]
