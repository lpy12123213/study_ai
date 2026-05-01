"""Question reviewer MCP tool using AI."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.llm.client import chat_completion
from backend.core.settings import (
    FIREWORKS_API_KEY,
    FIREWORKS_BASE_URL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    REVIEW_MAX_STEM_CHARS,
    REVIEW_MODEL,
    REVIEW_MODEL_MAX_TOKENS,
    REVIEW_MODEL_TEMPERATURE,
    REVIEW_PROVIDER,
    REVIEW_TIMEOUT,
)
from backend.generation.agentic.prompts import create_default_prompt_registry


def _prompt(prompt_id: str) -> str:
    return create_default_prompt_registry().render(prompt_id).content


REVIEW_SYSTEM_PROMPT = _prompt("mcp.question_reviewer.v1")


async def review_question(
    stem: str,
    answer: Optional[str] = None,
    analysis: Optional[str] = None,
    question_type: Optional[str] = None,
    subject: Optional[str] = None,
    difficulty: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Review a question using AI.

    Args:
        stem: The question text
        answer: The answer (if provided)
        analysis: The explanation/analysis (if provided)
        question_type: Type of question (e.g., multiple_choice, short_answer)
        subject: The subject area
        difficulty: Difficulty level (0-1)

    Returns:
        Dict with review results
    """
    # Determine which API to use
    if REVIEW_PROVIDER == "fireworks":
        api_key = FIREWORKS_API_KEY
        base_url = FIREWORKS_BASE_URL
    else:  # openrouter
        api_key = OPENROUTER_API_KEY
        base_url = OPENROUTER_BASE_URL

    if not api_key:
        return {
            "error": f"{REVIEW_PROVIDER} API key not configured",
            "verdict": "ERROR",
        }

    # Truncate stem if too long
    truncated_stem = stem[:REVIEW_MAX_STEM_CHARS]
    if len(stem) > REVIEW_MAX_STEM_CHARS:
        truncated_stem += "... [truncated]"

    # Build the review prompt
    prompt_parts = [
        "Please review the following exam question:",
        "",
        "**Question:**",
        truncated_stem,
    ]

    if answer:
        prompt_parts.extend(["", "**Answer:**", answer])
    if analysis:
        prompt_parts.extend(["", "**Analysis:**", analysis[:500]])
    if question_type:
        prompt_parts.extend(["", f"**Question Type:** {question_type}"])
    if subject:
        prompt_parts.extend(["", f"**Subject:** {subject}"])
    if difficulty is not None:
        prompt_parts.extend(["", f"**Difficulty:** {difficulty:.2f}"])

    prompt_parts.extend(
        [
            "",
            "Provide your detailed review following the structured format.",
        ]
    )

    user_prompt = "\n".join(prompt_parts)

    try:
        res = await chat_completion(
            messages=[
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=str(REVIEW_MODEL or "").strip(),
            temperature=float(REVIEW_MODEL_TEMPERATURE),
            max_tokens=int(REVIEW_MODEL_MAX_TOKENS or 0),
            stream=False,
            raise_on_fail=False,
            retries=3,
            timeout_s=float(REVIEW_TIMEOUT),
            req_id_prefix="reviewer",
            provider=str(REVIEW_PROVIDER or "").strip().lower(),
            base_url=str(base_url or "").strip(),
            api_key=str(api_key or "").strip(),
        )
        review_text = str(res.content or "").strip()
        if not review_text:
            return {"error": "No response from API", "verdict": "ERROR"}
        return _parse_review(review_text)
    except Exception as exc:
        return {"error": f"Review failed: {exc}", "verdict": "ERROR"}


def _parse_review(review_text: str) -> Dict[str, Any]:
    """Parse the review text to extract structured data."""
    result = {
        "raw_review": review_text,
        "overall_score": None,
        "clarity_score": None,
        "accuracy_score": None,
        "strengths": [],
        "weaknesses": [],
        "suggestions": [],
        "verdict": "NEEDS_REVISION",
    }

    # Try to extract scores
    lines = review_text.lower()

    if "approve" in lines:
        result["verdict"] = "APPROVE"
    elif "reject" in lines:
        result["verdict"] = "REJECT"

    # Extract numerical scores (simple heuristic)
    import re

    score_pattern = r"(\d+)\s*/\s*10"
    scores = re.findall(score_pattern, review_text)
    if scores:
        result["overall_score"] = int(scores[0])
        if len(scores) > 1:
            result["clarity_score"] = int(scores[1])
        if len(scores) > 2:
            result["accuracy_score"] = int(scores[2])

    return result


async def batch_review_questions(
    questions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Review multiple questions.

    Args:
        questions: List of question dicts with stem, answer, etc.

    Returns:
        List of review results
    """
    results = []
    for q in questions:
        review = await review_question(
            stem=q.get("stem", ""),
            answer=q.get("answer"),
            analysis=q.get("analysis"),
            question_type=q.get("question_type"),
            subject=q.get("subject"),
            difficulty=q.get("difficulty"),
        )
        results.append(review)
    return results


# ---------------------------------------------------------------------------
# Paper reviewer (batch) - used by MCP stdio server
# ---------------------------------------------------------------------------


def _get_batch_review_api_config() -> Dict[str, Any]:
    """Resolve API config for batch review based on REVIEW_PROVIDER."""
    if REVIEW_PROVIDER == "fireworks":
        model = REVIEW_MODEL
        if model and not model.startswith("accounts/"):
            model = f"accounts/fireworks/models/{model}"
        return {
            "api_key": FIREWORKS_API_KEY,
            "base_url": FIREWORKS_BASE_URL,
            "provider": "fireworks",
            "model": model,
        }

    return {
        "api_key": OPENROUTER_API_KEY,
        "base_url": OPENROUTER_BASE_URL,
        "provider": "openrouter",
        "model": REVIEW_MODEL,
    }


async def review_questions_with_openrouter(
    questions: List[Dict[str, Any]],
    paper_name: str = "",
    subject: str = "",
    focus: str = "",
    strictness: int = 3,
) -> Dict[str, Any]:
    """
    Review a list of questions (paper-level) using AI.

    Returns:
        {"success": bool, "review"?: str, "provider"?: str, "model"?: str, "error"?: str, ...}
    """
    api_config = _get_batch_review_api_config()

    if not api_config.get("api_key"):
        provider_name = "FIREWORKS_API_KEY" if REVIEW_PROVIDER == "fireworks" else "OPENROUTER_API_KEY"
        return {"success": False, "error": f"未配置 {provider_name}，请在 .env 文件中设置"}

    if not questions:
        return {"success": False, "error": "没有题目可供审查"}

    questions_text = ""
    for i, q in enumerate(questions, 1):
        stem = q.get("stem", "") or ""
        if not stem:
            stem = "(无题干内容)"

        if len(stem) > REVIEW_MAX_STEM_CHARS:
            stem = stem[:REVIEW_MAX_STEM_CHARS] + "..."

        questions_text += f"""
【第{i}题】
- ID: {q.get("question_id", "N/A")}
- 题型: {q.get("type", "未知")}
- 难度系数: {q.get("difficulty", "未知")}
- 知识点: {q.get("knowledge_points", "未知")}
- 题干: {stem}
"""

    strictness_desc = {
        1: "lenient: point out only obvious errors",
        2: "moderately lenient: point out errors and major problems",
        3: "balanced: point out errors, problems, and improvement suggestions",
        4: "strict: review carefully and propose optimizations",
        5: "very strict: review comprehensively from an exam-question expert perspective",
    }.get(int(strictness or 3), "balanced")

    focus_text = ""
    if (focus or "").strip():
        focus_text = f"""
## User special requirements (priority)
**{focus.strip()}**
Focus on the user requirements above during the review and respond to them first at the beginning of the report.
"""

    paper_info = f"Paper name: {paper_name}\n" if (paper_name or "").strip() else ""
    subject_info = f"Subject: {subject}\n" if (subject or "").strip() else ""

    prompt = f"""You are an experienced education expert and paper/question reviewer. Professionally review the following paper/questions.
Match the language of the user's request or the paper content for the final review unless another language is explicitly requested.

## Important note: data limitations
Images and mathematical formulas in the question text may have technical display issues. Ignore these technical issues during review:
- Images may appear as `[image]` placeholders and cannot be inspected.
- Mathematical formulas may appear as LaTeX code such as `$x^2$` or SVG tags such as `[formula:<svg...>]`.
- Some complex formulas may be incomplete or garbled after conversion.

Focus on the following reviewable content:
- Clarity and accuracy of wording.
- Question structure and logic.
- Difficulty distribution and knowledge-point coverage.
- Rationality of question-type mix.
- Clearly identifiable errors.

## Paper information
{paper_info}{subject_info}Question count: {len(questions)}
Review strictness: {int(strictness or 3)}/5 ({strictness_desc})
{focus_text}
## Question list
{questions_text}

## Review requirements
Review the following aspects:

1. Stem standards
   - Whether wording is clear and accurate.
   - Whether ambiguity or logical errors exist.
   - Whether sentences are fluent and complete.

2. Difficulty distribution
   - Whether difficulty is reasonably distributed.
   - Whether it fits the subject requirements.
   - Whether difficulty coefficients match actual difficulty.

3. Knowledge-point coverage
   - Whether knowledge points are balanced.
   - Whether any knowledge points are tested repeatedly.
   - Whether important knowledge points are missing.

4. Potential issues
   - Whether any question appears wrong based on readable text.
   - Whether any questions are duplicated or highly similar.
   - Whether any content is out of scope.

5. Overall evaluation
   - Overall quality score, 1-10.
   - Main strengths.
   - Main problems.
   - Improvement suggestions.

## Output format
Output clear, structured review comments directly. Do not output JSON.
"""

    try:
        res = await chat_completion(
            messages=[
                {"role": "system", "content": _prompt("mcp.paper_reviewer.v1")},
                {"role": "user", "content": prompt},
            ],
            model=str(api_config.get("model") or "").strip(),
            temperature=float(REVIEW_MODEL_TEMPERATURE),
            max_tokens=int(REVIEW_MODEL_MAX_TOKENS or 0),
            stream=False,
            raise_on_fail=False,
            retries=3,
            timeout_s=float(REVIEW_TIMEOUT),
            req_id_prefix="reviewer-batch",
            provider=str(api_config.get("provider") or "").strip().lower(),
            base_url=str(api_config.get("base_url") or "").strip(),
            api_key=str(api_config.get("api_key") or "").strip(),
        )

        content = str(res.content or "").strip()
        if not content:
            return {"success": False, "error": "AI 返回空内容", "provider": api_config.get("provider")}

        return {
            "success": True,
            "review": content,
            "provider": api_config.get("provider"),
            "model": api_config.get("model"),
            "strictness": int(strictness or 3),
            "questions_reviewed": len(questions),
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"请求错误: {exc}",
            "provider": api_config.get("provider"),
        }
