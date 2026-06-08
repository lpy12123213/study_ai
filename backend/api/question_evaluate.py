from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import require_auth
from backend.api.question_evaluate_schemas import (
    QuestionEvaluateRequest,
    QuestionEvaluateResponse,
    QuestionEvaluation,
    QuestionInput,
    QuestionSearchRequest,
    QuestionSearchResponse,
)
from backend.core.settings import DEFAULT_SUBJECT, LESSON_PLAN_MAX_TOKENS, LESSON_PLAN_MODEL, LESSON_PLAN_TEMPERATURE
from backend.core.subjects import resolve_subject
from backend.integrations.crawler.manager import get_crawler
from backend.llm.client import chat_completion_text
from backend.llm.prompts import create_default_prompt_registry
from backend.shared.tasks.runtime import RuntimeTask
from backend.tasks import submit_question_evaluate_task

router = APIRouter(prefix="/question-evaluate", tags=["question-evaluate"], dependencies=[Depends(require_auth)])


def _prompt(prompt_id: str) -> str:
    return create_default_prompt_registry().render(prompt_id).content


def _extract_json_obj(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    # Strip code fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw).lstrip()
        raw = re.sub(r"\s*```$", "", raw).rstrip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    candidate = raw[start : end + 1]
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return int(default)
    return int(v)


def _clip_list(items: Any, max_n: int) -> List[str]:
    out: List[str] = []
    if not isinstance(items, list):
        return out
    for it in items:
        s = str(it or "").strip()
        if not s:
            continue
        out.append(s)
        if len(out) >= max_n:
            break
    return out


def _normalize_verdict(overall_score: int) -> str:
    if overall_score >= 80:
        return "好题"
    if overall_score >= 60:
        return "普通题"
    return "差题"


def _normalize_dimensions(raw_dims: Any) -> List[Dict[str, Any]]:
    dims: List[Dict[str, Any]] = []
    if isinstance(raw_dims, list):
        for it in raw_dims:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()
            score = _coerce_int(it.get("score"), default=0)
            if score < 0:
                score = 0
            if score > 10:
                score = 10
            comment = str(it.get("comment") or "").strip()
            if not name:
                continue
            dims.append({"name": name, "score": score, "comment": comment})
    if dims:
        return dims
    return [
        {"name": "思维含量", "score": 0, "comment": ""},
        {"name": "区分度", "score": 0, "comment": ""},
        {"name": "知识覆盖", "score": 0, "comment": ""},
        {"name": "表述规范", "score": 0, "comment": ""},
        {"name": "创新性", "score": 0, "comment": ""},
    ]


def _response_from_task_payload(data: Dict[str, Any]) -> QuestionEvaluateResponse:
    raw_results = data.get("results") if isinstance(data.get("results"), list) else []
    results: List[QuestionEvaluation] = []
    for item in raw_results:
        if isinstance(item, QuestionEvaluation):
            results.append(item)
        elif isinstance(item, dict):
            results.append(QuestionEvaluation(**item))
    return QuestionEvaluateResponse(results=results, model=str(data.get("model") or ""))


async def _wait_question_evaluate_response(task: RuntimeTask) -> QuestionEvaluateResponse:
    while task.status == "running":
        async with task.cond:
            if task.status != "running":
                break
            try:
                await asyncio.wait_for(task.cond.wait(), timeout=30)
            except asyncio.TimeoutError:
                continue

    if task.status != "completed":
        message = task.error or "question_evaluate_failed"
        raise HTTPException(status_code=500, detail=message)

    result = task.meta.get("result") if isinstance(task.meta.get("result"), dict) else None
    if not isinstance(result, dict):
        for event in reversed(task.events):
            if str(event.get("type") or "") == "done" and isinstance(event.get("data"), dict):
                result = event.get("data")
                break
    return _response_from_task_payload(result or {})


async def _evaluate_one(
    q: QuestionInput,
    *,
    subject: str,
    requirements: str,
    model: str,
) -> QuestionEvaluation:
    stem = (q.stem or "").strip()
    stem = stem[:1500]

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

    prompt = json.dumps(payload, ensure_ascii=False)

    text = await chat_completion_text(
        messages=[
            {
                "role": "system",
                "content": _prompt("question.evaluate.external.v1"),
            },
            {"role": "user", "content": prompt},
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

    overall = _coerce_int(obj.get("overall_score"), default=0)
    if overall < 0:
        overall = 0
    if overall > 100:
        overall = 100

    verdict = str(obj.get("verdict") or "").strip()
    if verdict not in {"好题", "普通题", "差题"}:
        verdict = _normalize_verdict(overall)

    dims = _normalize_dimensions(obj.get("dimensions"))

    highlights = _clip_list(obj.get("highlights"), 8)
    issues = _clip_list(obj.get("issues"), 8)
    summary = str(obj.get("summary") or "").strip()

    return QuestionEvaluation(
        question_id=(q.question_id or "").strip(),
        verdict=verdict,
        overall_score=overall,
        dimensions=[
            {
                "name": str(d.get("name") or ""),
                "score": _coerce_int(d.get("score"), default=0),
                "comment": str(d.get("comment") or ""),
            }
            for d in dims
        ],
        highlights=highlights,
        issues=issues,
        summary=summary,
    )


async def evaluate_generated_question_review(
    *,
    subject: str,
    stem: str,
    answer: str,
    analysis: str,
    requirements: str = "",
    model: str = "",
) -> Dict[str, Any]:
    resolved_subject = resolve_subject((subject or "").strip() or DEFAULT_SUBJECT, strict=True)
    resolved_model = (model or "").strip() or str(LESSON_PLAN_MODEL or "").strip()
    if not resolved_model:
        raise RuntimeError("llm_model_not_configured")

    payload = {
        "subject": resolved_subject,
        "requirements": (requirements or "").strip(),
        "question": {
            "stem": str(stem or "").strip()[:1600],
            "answer": str(answer or "").strip()[:1200],
            "analysis": str(analysis or "").strip()[:2000],
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
            {
                "role": "system",
                "content": _prompt("question.judge.quality.v1"),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=resolved_model,
        temperature=float(LESSON_PLAN_TEMPERATURE),
        max_tokens=int(LESSON_PLAN_MAX_TOKENS),
        response_format={"type": "json_object"},
        reasoning={"effort": "high", "exclude": True},
        stream=False,
        raise_on_fail=False,
        retries=3,
        req_id_prefix="qe_review",
    )

    obj = _extract_json_obj(text)
    overall = _coerce_int(obj.get("overall_score"), default=0)
    overall = max(0, min(100, overall))
    verdict = str(obj.get("verdict") or "").strip()
    if verdict not in {"好题", "普通题", "差题"}:
        verdict = _normalize_verdict(overall)

    return {
        "verdict": verdict,
        "overall_score": overall,
        "dimensions": _normalize_dimensions(obj.get("dimensions")),
        "highlights": _clip_list(obj.get("highlights"), 8),
        "issues": _clip_list(obj.get("issues"), 8),
        "summary": str(obj.get("summary") or "").strip(),
        "model": resolved_model,
    }


@router.post("/search", response_model=QuestionSearchResponse)
async def search_questions(payload: QuestionSearchRequest) -> QuestionSearchResponse:
    query = (payload.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="missing_query")

    subject_input = (payload.subject or DEFAULT_SUBJECT).strip()
    edu_level = (payload.edu_level or "").strip()
    try:
        subject = resolve_subject(subject_input, edu_level=edu_level, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    crawler = await get_crawler(subject=subject, edu_level=edu_level, strict=True)

    result = await crawler.search_by_keyword(
        keyword=query,
        subject=subject,
        edu_level=edu_level,
        limit=int(payload.limit or 20),
        difficulty=(payload.difficulty or "").strip(),
        question_type=(payload.question_type or "").strip(),
        max_pages=int(payload.max_pages or 2),
        dedup_by_stem=True,
        min_quality_score=int(payload.min_quality_score or 0),
        with_quality=True,
        require_difficulty=False,
        strict_subject=True,
    )

    if not isinstance(result, dict) or not result.get("success"):
        return QuestionSearchResponse(
            success=False,
            query=query,
            subject=subject,
            count=0,
            questions=[],
            error=str((result or {}).get("error") or "search_failed"),
        )

    raw_questions = result.get("questions") or []
    out_questions: List[QuestionInput] = []
    for q in raw_questions:
        if not isinstance(q, dict):
            continue

        kp_val = q.get("knowledge_points")
        if isinstance(kp_val, list):
            kp_text = "、".join([str(x) for x in kp_val if str(x or "").strip()])
        else:
            kp_text = str(kp_val or "").strip()
        out_questions.append(
            QuestionInput(
                question_id=str(q.get("question_id") or "").strip(),
                stem=str(q.get("stem") or "").strip(),
                type=str(q.get("type") or "").strip(),
                difficulty=str(q.get("difficulty") or "").strip(),
                knowledge_points=kp_text,
                source=str(q.get("source") or "").strip(),
                source_url=str(q.get("source_url") or "").strip(),
                date=str(q.get("date") or "").strip(),
                quality_score=q.get("quality_score") if isinstance(q.get("quality_score"), int) else None,
                quality_flags=list(q.get("quality_flags") or []) if isinstance(q.get("quality_flags"), list) else [],
                difficulty_value=q.get("difficulty_value")
                if isinstance(q.get("difficulty_value"), (int, float))
                else None,
            )
        )

    return QuestionSearchResponse(
        success=True,
        query=query,
        subject=subject,
        count=len(out_questions),
        questions=out_questions,
        error="",
    )


@router.post("/evaluate", response_model=QuestionEvaluateResponse)
async def evaluate_questions(payload: QuestionEvaluateRequest, user: dict = Depends(require_auth)) -> QuestionEvaluateResponse:
    if not payload.questions:
        raise HTTPException(status_code=400, detail="missing_questions")

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    task = await submit_question_evaluate_task(user_id=user_id, request=payload.model_dump())
    return await _wait_question_evaluate_response(task)
