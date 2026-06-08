from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from backend.core.logging_utils import get_logger
from backend.core.settings import LESSON_PLAN_MAX_TOKENS, LESSON_PLAN_MODEL, LESSON_PLAN_TEMPERATURE
from backend.llm.client import chat_completion_text, is_llm_configured
from backend.llm.prompts import create_default_prompt_registry

logger = get_logger(__name__)


def _safe_extract_json(text: str) -> dict:
    raw = str(text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(raw[start : end + 1])
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _fallback_grade(*, answer_data: Dict[str, Any], max_score: float) -> Dict[str, Any]:
    text = str(answer_data.get("text_answer") or answer_data.get("textAnswer") or "").strip()
    image_path = str(answer_data.get("handwriting_image_path") or answer_data.get("handwritingImagePath") or "").strip()
    if not text and not image_path:
        score = 0.0
        reason = "未作答"
    elif text:
        score = 0.0
        reason = "未配置视觉/评分模型，主观题需人工复核，暂不给分。"
    else:
        score = 0.0
        reason = "已提交手写图片，未配置视觉模型，需人工复核，暂不给分。"
    return {
        "is_correct": None,
        "score": score,
        "max_score": float(max_score or 0.0),
        "grading_json": {
            "mode": "fallback",
            "reasoning": reason,
            "strengths": [],
            "weaknesses": [],
        },
    }


async def grade_subjective_answer(
    *,
    question: Dict[str, Any],
    answer_data: Dict[str, Any],
    max_score: float,
) -> Dict[str, Any]:
    """Grade subjective answers with LLM when available, otherwise return a deterministic fallback."""

    if not is_llm_configured():
        return _fallback_grade(answer_data=answer_data, max_score=max_score)

    model = (LESSON_PLAN_MODEL or "").strip()
    if not model:
        return _fallback_grade(answer_data=answer_data, max_score=max_score)

    text_answer = str(answer_data.get("text_answer") or answer_data.get("textAnswer") or "").strip()
    image_path = str(answer_data.get("handwriting_image_path") or answer_data.get("handwritingImagePath") or "").strip()
    image_note = ""
    if image_path:
        name = Path(image_path).name[:120]
        image_note = f"\n学生提交了手写图片文件：{name}。当前文本通道不能直接读取图片时，请按文字补充谨慎评分。"

    prompt = "\n".join(
        [
            "你是严谨的中学试卷阅卷老师。请按参考答案和评分标准给主观题打分。",
            "输出严格 JSON，字段为 score, max_score, reasoning, strengths, weaknesses。",
            f"满分：{float(max_score or 0.0)}",
            f"题干：{str(question.get('stem') or '').strip()}",
            f"参考答案：{str(question.get('answer') or '').strip()}",
            f"解析：{str(question.get('analysis') or '').strip()}",
            f"学生文字作答：{text_answer or '（无）'}{image_note}",
        ]
    )
    try:
        text = await chat_completion_text(
            messages=[
                {
                    "role": "system",
                    "content": create_default_prompt_registry().render("exam.subjective.grade.v1").content,
                },
                {"role": "user", "content": prompt},
            ],
            model=model,
            temperature=float(LESSON_PLAN_TEMPERATURE or 0.2),
            max_tokens=int(LESSON_PLAN_MAX_TOKENS or 1200),
        )
        payload = _safe_extract_json(text)
        score = float(payload.get("score") or 0.0)
        score = max(0.0, min(score, float(max_score or 0.0)))
        return {
            "is_correct": None,
            "score": score,
            "max_score": float(max_score or 0.0),
            "grading_json": {
                "mode": "llm",
                "reasoning": str(payload.get("reasoning") or "").strip(),
                "strengths": payload.get("strengths") if isinstance(payload.get("strengths"), list) else [],
                "weaknesses": payload.get("weaknesses") if isinstance(payload.get("weaknesses"), list) else [],
            },
        }
    except (RuntimeError, TypeError, ValueError):
        logger.warning("exam_subjective_grading_failed", exc_info=True)
        return _fallback_grade(answer_data=answer_data, max_score=max_score)
