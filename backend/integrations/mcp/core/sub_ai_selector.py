"""
子AI选题服务 - 从候选题目中选择最符合要求的题目
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.core.settings import (
    SUB_AI_TIMEOUT,
    SUB_MODEL,
    SUB_MODEL_MAX_TOKENS,
    SUB_MODEL_TEMPERATURE,
)
from backend.llm.client import chat_completion, is_llm_configured
from backend.llm.prompts import create_default_prompt_registry

logger = get_logger(__name__)


def _prompt(prompt_id: str, **values: Any) -> str:
    return create_default_prompt_registry().render(prompt_id, **values).content


async def select_best_question(
    questions: List[Dict[str, Any]],
    requirement: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用子AI从候选题目中选择最符合要求的一道。

    Args:
        questions: 候选题目列表，每个题目包含 question_id, stem, type, difficulty 等
        requirement: 选题要求描述

    Returns:
        {
            "success": True/False,
            "selected_question_id": "选中的题目ID",
            "reason": "选择理由",
            "analysis": "各题目分析"
        }
    """

    if not questions:
        return {"success": False, "error": "没有候选题目"}

    effective_model = (model or SUB_MODEL).strip() or SUB_MODEL

    # We keep the contract simple here: use the same OpenAI-compatible endpoint as chat,
    # and rely on the shared `backend.llm.client.chat_completion(...)` for provider resolution,
    # headers, retries and streaming semantics.
    if not is_llm_configured(scope="chat"):
        return {"success": False, "error": "llm_not_configured"}

    # Build question description text
    questions_text = ""
    for i, q in enumerate(questions, 1):
        stem = q.get("stem", "")
        if not stem:
            stem = "(无题干内容)"

        questions_text += f"""
【题目{i}】
- ID: {q.get("question_id", "N/A")}
- 题型: {q.get("type", "未知")}
- 难度系数: {q.get("difficulty", "未知")}
- 知识点: {q.get("knowledge_points", "未知")}
- 题干内容: {stem}
"""

    # Build a short, strict prompt to reduce format drift.
    prompt = _prompt(
        "mcp.sub_ai_selector.user.v1",
        requirement=requirement,
        questions_count=len(questions),
        questions_text=questions_text,
    )

    try:
        res = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model=effective_model,
            temperature=float(SUB_MODEL_TEMPERATURE),
            max_tokens=int(SUB_MODEL_MAX_TOKENS),
            stream=False,
            raise_on_fail=False,
            retries=3,
            timeout_s=float(SUB_AI_TIMEOUT or 60),
            req_id_prefix="subai",
            scope="chat",
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("sub_ai_selector_request_failed")
        return {"success": False, "error": f"请求错误: {str(exc)}"}

    content = str(res.content or "")
    if not content.strip():
        return {"success": False, "error": "AI响应为空"}

    # Parse JSON response (tolerate markdown fences).
    try:
        json_match = re.search(r"\{[\s\S]*\}", content)
        if not json_match:
            return {"success": False, "error": "无法解析AI响应", "raw_response": content[:500]}

        result = json.loads(json_match.group())
        if not isinstance(result, dict):
            return {"success": False, "error": "无法解析AI响应", "raw_response": content[:500]}

        # Validate and normalize fields (best-effort).
        question_ids = [str(q.get("question_id", "")).strip() for q in questions]
        id_to_index = {qid: idx for idx, qid in enumerate(question_ids) if qid}

        selected_question_id_raw = result.get("selected_question_id")
        selected_question_id = str(selected_question_id_raw).strip() if selected_question_id_raw is not None else ""

        if selected_question_id and selected_question_id in id_to_index:
            selected_idx = id_to_index[selected_question_id]
        else:
            selected_index_raw = result.get("selected_index", 1)
            try:
                selected_index = int(selected_index_raw)
            except (TypeError, ValueError):
                selected_index = 1

            if selected_index < 1:
                selected_index = 1
            if selected_index > len(questions):
                selected_index = len(questions)

            selected_idx = selected_index - 1
            selected_question_id = question_ids[selected_idx]

        result["selected_index"] = selected_idx + 1
        if selected_question_id:
            result["selected_question_id"] = selected_question_id

        result["success"] = True
        return result
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"JSON解析失败: {str(exc)}", "raw_response": content[:500]}
