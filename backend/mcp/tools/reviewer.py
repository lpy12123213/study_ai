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

REVIEW_SYSTEM_PROMPT = """You are an expert educational content reviewer.
Your task is to evaluate exam questions for quality, accuracy, and pedagogical value.

When reviewing a question, consider:
1. Clarity: Is the question clearly worded and unambiguous?
2. Accuracy: Is the content factually correct?
3. Difficulty: Is the difficulty level appropriate for the target audience?
4. Educational value: Does it test meaningful learning objectives?
5. Answer quality: Is the provided answer correct and complete?
6. Analysis quality: Is the explanation helpful for learning?

Provide your review in a structured format with:
- Overall score (1-10)
- Clarity score (1-10)
- Accuracy score (1-10)
- Strengths (list)
- Weaknesses (list)
- Suggestions for improvement (list)
- Verdict: APPROVE, NEEDS_REVISION, or REJECT"""


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
        1: "宽松（只指出明显错误）",
        2: "较宽松（指出错误和较大问题）",
        3: "适中（指出错误、问题和改进建议）",
        4: "较严格（细致审查，提出优化意见）",
        5: "非常严格（从考试命题专家角度全面审查）",
    }.get(int(strictness or 3), "适中")

    focus_text = ""
    if (focus or "").strip():
        focus_text = f"""
## 🎯 用户特别要求（优先关注）
**{focus.strip()}**
请在审查时重点关注上述用户要求，并在报告开头首先回应这一诉求。
"""

    paper_info = f"试卷名称: {paper_name}\n" if (paper_name or "").strip() else ""
    subject_info = f"学科: {subject}\n" if (subject or "").strip() else ""

    prompt = f"""你是一位经验丰富的教育专家和试卷审查员。请对以下试卷/题目进行专业审查。

## ⚠️ 重要提示：数据局限性
题干中的**图片和数学公式**可能存在以下问题，请在审查时**忽略这些技术性问题**：
- 图片显示为 `[图片]` 占位符，无法查看具体内容
- 数学公式可能显示为 LaTeX 代码（如 `$x^2$`）或 SVG 标签（如 `[公式:<svg...>]`）
- 部分复杂公式可能转换不完整或有乱码

**请专注于以下可审查的内容：**
- 文字表述的清晰度和准确性
- 题目结构和逻辑
- 难度分布和知识点覆盖
- 题型搭配的合理性
- 可识别的明显错误

## 试卷信息
{paper_info}{subject_info}题目数量: {len(questions)}
审查严格度: {int(strictness or 3)}/5 ({strictness_desc})
{focus_text}
## 题目列表
{questions_text}

## 审查要求
请从以下方面进行审查：

1. **题干规范性**
   - 文字表述是否清晰、准确
   - 是否存在歧义或逻辑错误
   - 语句是否通顺完整

2. **难度分布**
   - 难度是否合理分布
   - 是否符合该学科要求
   - 难度系数是否与实际难度匹配

3. **知识点覆盖**
   - 知识点分布是否均衡
   - 是否有重复考查的知识点
   - 是否有重要知识点遗漏

4. **潜在问题**
   - 是否有疑似错题（基于可读的文字部分判断）
   - 是否有重复或高度相似的题目
   - 是否有超纲内容

5. **综合评价**
   - 整体质量评分（1-10分）
   - 主要优点
   - 主要问题
   - 改进建议

## 输出格式
请以清晰、结构化的方式输出审查意见，直接用中文回复，不需要JSON格式。
"""

    try:
        res = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
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
