"""Essay evaluation core service.

Single function ``evaluate_essay`` calls the configured chat completion API
with a structured-JSON prompt and normalises the response into an
:class:`EssayEvaluationResult`. The runner module wraps this with TaskRuntime
SSE progress events; the API also accepts a one-shot synchronous call.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.core.settings import LESSON_PLAN_MAX_TOKENS, LESSON_PLAN_MODEL, LESSON_PLAN_TEMPERATURE
from backend.generation.essay_evaluation.essay_parser import ParsedEssay, parse_essay
from backend.generation.essay_evaluation.essay_schemas import (
    EssayEvaluationRequest,
    EssayEvaluationResult,
    EssayParagraphFeedback,
    EssayScore,
)
from backend.llm.client import chat_completion_text, is_llm_configured

logger = get_logger(__name__)


ProgressCallback = Callable[[int, str], Awaitable[None]]


# --------------------------------------------------------------------------- #
# Rubric definitions                                                           #
# --------------------------------------------------------------------------- #


_DEFAULT_RUBRIC_ZH: List[Dict[str, Any]] = [
    {"name": "内容立意", "weight": 0.25, "max_score": 10, "description": "立意是否深刻、紧扣题意、观点鲜明"},
    {"name": "结构布局", "weight": 0.20, "max_score": 10, "description": "段落层次清晰、过渡自然、首尾呼应"},
    {"name": "语言表达", "weight": 0.25, "max_score": 10, "description": "用词准确、句式多样、语言生动"},
    {"name": "论证逻辑", "weight": 0.20, "max_score": 10, "description": "论据充分、推理严密、说服力强"},
    {"name": "文采创新", "weight": 0.10, "max_score": 10, "description": "表达有亮点、视角或结构有创新"},
]

_DEFAULT_RUBRIC_EN: List[Dict[str, Any]] = [
    {"name": "Task Response", "weight": 0.30, "max_score": 10, "description": "Addresses all parts of the prompt with a clear position"},
    {"name": "Coherence & Cohesion", "weight": 0.20, "max_score": 10, "description": "Logical organization, paragraphing, cohesive devices"},
    {"name": "Lexical Resource", "weight": 0.20, "max_score": 10, "description": "Range and accuracy of vocabulary"},
    {"name": "Grammatical Range", "weight": 0.20, "max_score": 10, "description": "Variety and accuracy of grammatical structures"},
    {"name": "Style", "weight": 0.10, "max_score": 10, "description": "Tone, register, originality"},
]


def _select_rubric(language: str) -> List[Dict[str, Any]]:
    return _DEFAULT_RUBRIC_EN if language == "en" else _DEFAULT_RUBRIC_ZH


def _scale_to_total(raw_scores: List[EssayScore], target_total: int) -> tuple[float, float]:
    """Map per-dimension raw scores to the user-requested rubric total.

    ``target_total`` is e.g. 60 for 高考语文. We sum weighted raw fractions then
    multiply by the target. Returns ``(score_total, score_max)``.
    """

    if not raw_scores:
        return 0.0, float(target_total)

    total_weight = sum(max(0.0, float(s.weight)) for s in raw_scores) or 1.0
    weighted_fraction = 0.0
    for s in raw_scores:
        w = max(0.0, float(s.weight)) / total_weight
        denom = max(1.0, float(s.max_score or 0.0))
        ratio = max(0.0, min(1.0, float(s.score or 0.0) / denom))
        weighted_fraction += w * ratio
    return round(weighted_fraction * target_total, 1), float(target_total)


# --------------------------------------------------------------------------- #
# Prompt building                                                              #
# --------------------------------------------------------------------------- #


def _build_prompt(*, request: EssayEvaluationRequest, parsed: ParsedEssay, rubric: List[Dict[str, Any]]) -> str:
    rubric_lines = [
        f"- {item['name']}（权重 {item['weight']}，满分 {item['max_score']}）：{item['description']}"
        for item in rubric
    ]
    paragraph_excerpts = []
    for para in parsed.paragraphs:
        snippet = para.text if len(para.text) <= 200 else para.text[:200] + "…"
        paragraph_excerpts.append(f"[段{para.index + 1}|字数{para.char_count}|句数{para.sentence_count}] {snippet}")

    instructions = "\n".join(
        [
            "你是一位经验丰富的中高考阅卷老师，请按照以下评分维度对作文进行结构化批改。",
            "输出**严格的 JSON 对象**，禁止任何解释性文字、Markdown 或代码块标记。",
            "",
            f"评分语言：{'英文 (English)' if request.language == 'en' else '中文'}",
            f"作文文体：{request.essay_type}",
            f"年段：{request.grade_band}",
            f"科目：{request.subject}",
            f"题目：{request.topic or '（未给出题目）'}",
            f"评分总分：{int(request.rubric_max_score)} 分（最终 score_total 必须落在 [0, {int(request.rubric_max_score)}]）。",
            f"附加要求：{request.requirements or '（无）'}",
            "",
            "评分维度（每项给 0-10 整数分，并附 ≤ 60 字的简评）：",
            *rubric_lines,
            "",
            "请同时给出：",
            "1) 总评 summary：120 字以内的总体评价；",
            "2) strengths/weaknesses：各 ≤ 4 条要点，每条 ≤ 30 字；",
            "3) suggestions：≤ 4 条修改建议，每条 ≤ 40 字；",
            "4) paragraph_feedback：针对最多 6 个关键段的逐段问题与建议（index 从 0 开始，对应下方段落顺序）；",
            "5) rewrite：可选，给出一段 ≤ 200 字的关键段落改写示例（无则留空字符串）；",
            "6) score_total：根据上述维度按权重综合，已映射到本次满分 (含一位小数)。",
            "",
            "请严格按照如下 JSON 结构输出：",
            "{",
            '  "scores": [{"name": "...", "score": 0, "max_score": 10, "weight": 0.25, "comment": "..."}],',
            '  "score_total": 0.0,',
            '  "summary": "...",',
            '  "grade": "优秀|良好|合格|待提升",',
            '  "strengths": ["..."], "weaknesses": ["..."], "suggestions": ["..."],',
            '  "paragraph_feedback": [{"index": 0, "excerpt": "...", "issues": ["..."], "suggestion": "..."}],',
            '  "rewrite": "..."',
            "}",
            "",
            f"作文统计：字数 {parsed.char_count}，词数 {parsed.word_count}，句数 {parsed.sentence_count}，段落 {parsed.paragraph_count}。",
            "",
            "作文段落：",
            *paragraph_excerpts,
            "",
            "原文（用 ``` 包裹，仅供参考，不要照抄）：",
            "```",
            parsed.cleaned,
            "```",
        ]
    )

    return instructions


def _safe_extract_json(text: str) -> Dict[str, Any]:
    """Robust JSON extractor that survives leading/trailing chatter."""

    raw = (text or "").strip()
    if not raw:
        return {}
    # Strip code fences.
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw).lstrip()
        raw = re.sub(r"\s*```$", "", raw).rstrip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(raw[start : end + 1])
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


# --------------------------------------------------------------------------- #
# Normalization                                                                #
# --------------------------------------------------------------------------- #


def _normalize_scores(raw_scores: Any, rubric: List[Dict[str, Any]]) -> List[EssayScore]:
    """Coerce LLM scores into the rubric, filling missing dimensions with zeros."""

    scored: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw_scores, list):
        for item in raw_scores:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            scored[name] = item

    out: List[EssayScore] = []
    for item in rubric:
        name = item["name"]
        max_score = float(item["max_score"])
        weight = float(item["weight"])
        raw = scored.get(name, {})
        try:
            score = float(raw.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(score, max_score))
        out.append(
            EssayScore(
                name=name,
                score=score,
                max_score=max_score,
                weight=weight,
                comment=str(raw.get("comment") or "").strip()[:200],
            )
        )
    return out


def _normalize_paragraph_feedback(raw: Any, *, max_index: int) -> List[EssayParagraphFeedback]:
    out: List[EssayParagraphFeedback] = []
    if not isinstance(raw, list):
        return out
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index") or 0)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx > max_index:
            continue
        issues = item.get("issues") or []
        if not isinstance(issues, list):
            issues = [str(issues)]
        out.append(
            EssayParagraphFeedback(
                index=idx,
                excerpt=str(item.get("excerpt") or "")[:400],
                issues=[str(x).strip() for x in issues if str(x).strip()][:5],
                suggestion=str(item.get("suggestion") or "")[:400],
            )
        )
    return out


def _string_list(raw: Any, *, limit: int = 5, max_len: int = 200) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        s = str(item or "").strip()
        if not s:
            continue
        out.append(s[:max_len])
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #


async def evaluate_essay(
    request: EssayEvaluationRequest,
    *,
    model: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> EssayEvaluationResult:
    """Evaluate an essay end-to-end and return a structured rubric result.

    ``on_progress`` is invoked with ``(percent, stage_label)`` so callers
    (FastAPI SSE endpoint, TaskRuntime runner) can stream progress without
    knowing the internal phases.
    """

    if not is_llm_configured():
        raise RuntimeError("llm_not_configured")

    parsed = parse_essay(request.text)
    if parsed.char_count < 10:
        raise ValueError("essay_too_short")

    if on_progress:
        await on_progress(10, "parse")

    language = request.language or parsed.language_hint
    rubric = _select_rubric(language)

    if on_progress:
        await on_progress(25, "prompt")

    prompt = _build_prompt(request=request.model_copy(update={"language": language}), parsed=parsed, rubric=rubric)
    chosen_model = (model or LESSON_PLAN_MODEL or "").strip()
    if not chosen_model:
        raise RuntimeError("llm_model_not_configured")

    if on_progress:
        await on_progress(40, "llm")

    text = await chat_completion_text(
        messages=[
            {"role": "system", "content": "你是一位严谨、专业的中文/英文作文阅卷教师。"},
            {"role": "user", "content": prompt},
        ],
        model=chosen_model,
        temperature=float(LESSON_PLAN_TEMPERATURE or 0.3),
        max_tokens=int(LESSON_PLAN_MAX_TOKENS or 2000),
    )

    if on_progress:
        await on_progress(80, "parse_response")

    payload = _safe_extract_json(text)
    scores = _normalize_scores(payload.get("scores"), rubric)
    score_total, score_max = _scale_to_total(scores, request.rubric_max_score)

    # Trust the LLM's score_total only when it is within tolerance of our
    # weighted re-computation, otherwise prefer the deterministic value.
    try:
        llm_total = float(payload.get("score_total") or 0.0)
    except (TypeError, ValueError):
        llm_total = 0.0
    if 0 <= llm_total <= score_max and abs(llm_total - score_total) <= max(2.0, score_max * 0.1):
        score_total = round(llm_total, 1)

    paragraph_feedback = _normalize_paragraph_feedback(
        payload.get("paragraph_feedback"),
        max_index=max(0, parsed.paragraph_count - 1),
    )

    grade = str(payload.get("grade") or "").strip()
    if not grade:
        ratio = score_total / max(score_max, 1.0)
        if ratio >= 0.85:
            grade = "优秀" if language != "en" else "Excellent"
        elif ratio >= 0.70:
            grade = "良好" if language != "en" else "Good"
        elif ratio >= 0.55:
            grade = "合格" if language != "en" else "Pass"
        else:
            grade = "待提升" if language != "en" else "Needs Improvement"

    result = EssayEvaluationResult(
        score_total=float(score_total),
        score_max=float(score_max),
        grade=grade[:32],
        summary=str(payload.get("summary") or "").strip()[:600],
        strengths=_string_list(payload.get("strengths"), limit=5, max_len=120),
        weaknesses=_string_list(payload.get("weaknesses"), limit=5, max_len=120),
        suggestions=_string_list(payload.get("suggestions"), limit=5, max_len=200),
        scores=scores,
        paragraph_feedback=paragraph_feedback,
        rewrite=str(payload.get("rewrite") or "").strip()[:1500],
        model=chosen_model,
        language=language,
        essay_type=request.essay_type,
        grade_band=request.grade_band,
    )

    if on_progress:
        await on_progress(100, "done")

    return result


__all__ = ["evaluate_essay"]
