from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.api.question_evaluate_schemas import QuestionEvaluation, QuestionInput
from backend.core.settings import LESSON_PLAN_MAX_TOKENS, LESSON_PLAN_MODEL, LESSON_PLAN_TEMPERATURE
from backend.core.subjects import resolve_subject
from backend.llm.prompts import create_default_prompt_registry
from backend.llm.client import chat_completion_text

ProgressCallback = Callable[[int, int, QuestionEvaluation], Awaitable[None]]


def _prompt(prompt_id: str) -> str:
    return create_default_prompt_registry().render(prompt_id).content


def _extract_json_obj(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw).lstrip()
        raw = re.sub(r"\s*```$", "", raw).rstrip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(raw[start : end + 1])
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _clip_list(items: Any, max_n: int) -> List[str]:
    out: List[str] = []
    if not isinstance(items, list):
        return out
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        out.append(value)
        if len(out) >= max_n:
            break
    return out


def _normalize_verdict(overall_score: int) -> str:
    if overall_score >= 80:
        return "好题"
    if overall_score >= 60:
        return "普通题"
    return "差题"


def _normalize_dimensions(raw: Any) -> List[Dict[str, Any]]:
    dims: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw[:8]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            score = max(0, min(10, _coerce_int(item.get("score"), default=0)))
            comment = str(item.get("comment") or "").strip()
            if name:
                dims.append({"name": name, "score": score, "comment": comment})
    return dims or [
        {"name": "思维含量", "score": 0, "comment": ""},
        {"name": "区分度", "score": 0, "comment": ""},
        {"name": "知识覆盖", "score": 0, "comment": ""},
        {"name": "表述规范", "score": 0, "comment": ""},
        {"name": "创新性", "score": 0, "comment": ""},
    ]


async def evaluate_one_question(
    q: QuestionInput,
    *,
    subject: str,
    requirements: str,
    model: str,
) -> QuestionEvaluation:
    stem = (q.stem or "").strip()[:1500]

    heuristics: List[str] = []
    if q.quality_score is not None:
        heuristics.append(f"crawler_quality_score={int(q.quality_score)}")
    if q.quality_flags:
        heuristics.append(f"crawler_quality_flags={', '.join([str(x) for x in q.quality_flags[:8]])}")
    if q.difficulty_value is not None:
        heuristics.append(f"difficulty_value={q.difficulty_value}")

    payload = {
        "subject": subject,
        "requirements": (requirements or "").strip(),
        "question": {
            "question_id": (q.question_id or "").strip(),
            "type": (q.type or "").strip(),
            "difficulty": (q.difficulty or "").strip(),
            "knowledge_points": (q.knowledge_points or "").strip(),
            "source": (q.source or "").strip(),
            "date": (q.date or "").strip(),
            "source_url": (q.source_url or "").strip(),
            "stem": stem,
            "heuristics": heuristics,
        },
        "output_schema": {
            "verdict": "string (好题|普通题|差题)",
            "overall_score": "int 0-100",
            "dimensions": [
                {"name": "思维含量", "score": "int 1-10", "comment": "string"},
                {"name": "区分度", "score": "int 1-10", "comment": "string"},
                {"name": "知识覆盖", "score": "int 1-10", "comment": "string"},
                {"name": "表述规范", "score": "int 1-10", "comment": "string"},
                {"name": "创新性", "score": "int 1-10", "comment": "string"},
            ],
            "highlights": "string[]",
            "issues": "string[]",
            "summary": "string",
        },
    }

    text = await chat_completion_text(
        messages=[
            {"role": "system", "content": _prompt("question.evaluate.external.v1")},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=model,
        temperature=float(LESSON_PLAN_TEMPERATURE),
        max_tokens=int(LESSON_PLAN_MAX_TOKENS),
        response_format={"type": "json_object"},
        reasoning={"effort": "high", "exclude": True},
        stream=False,
        raise_on_fail=False,
        retries=3,
        req_id_prefix="qe",
    )

    obj = _extract_json_obj(text)
    overall = max(0, min(100, _coerce_int(obj.get("overall_score"), default=0)))
    verdict = str(obj.get("verdict") or "").strip()
    if verdict not in {"好题", "普通题", "差题"}:
        verdict = _normalize_verdict(overall)

    return QuestionEvaluation(
        question_id=(q.question_id or "").strip(),
        verdict=verdict,
        overall_score=overall,
        dimensions=[
            {
                "name": str(dim.get("name") or ""),
                "score": _coerce_int(dim.get("score"), default=0),
                "comment": str(dim.get("comment") or ""),
            }
            for dim in _normalize_dimensions(obj.get("dimensions"))
        ],
        highlights=_clip_list(obj.get("highlights"), 8),
        issues=_clip_list(obj.get("issues"), 8),
        summary=str(obj.get("summary") or "").strip(),
    )


async def evaluate_questions_batch(
    *,
    questions: List[QuestionInput],
    subject: str,
    requirements: str,
    model: str,
    on_progress: Optional[ProgressCallback] = None,
) -> List[QuestionEvaluation]:
    resolved_subject = resolve_subject((subject or "").strip(), strict=True)
    resolved_model = (model or "").strip() or str(LESSON_PLAN_MODEL or "").strip()
    if not resolved_model:
        raise RuntimeError("llm_model_not_configured")

    sem = asyncio.Semaphore(4)
    completed = 0

    async def _run(q: QuestionInput) -> QuestionEvaluation:
        nonlocal completed
        async with sem:
            result = await evaluate_one_question(
                q,
                subject=resolved_subject,
                requirements=requirements,
                model=resolved_model,
            )
        completed += 1
        if on_progress is not None:
            await on_progress(completed, len(questions), result)
        return result

    gathered = await asyncio.gather(*[_run(q) for q in questions[:50]], return_exceptions=True)
    results = [item for item in gathered if isinstance(item, QuestionEvaluation)]
    return sorted(results, key=lambda item: int(getattr(item, "overall_score", 0) or 0), reverse=True)
