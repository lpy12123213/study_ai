"""
子AI选题服务 - 从候选题目中选择最符合要求的题目
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from backend.core.settings import (
    SUB_AI_TIMEOUT,
    SUB_MODEL,
    SUB_MODEL_MAX_TOKENS,
    SUB_MODEL_TEMPERATURE,
)
from backend.llm.client import chat_completion, is_llm_configured


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
    prompt = f"""你是一个专业的选题助手。请根据“选题要求”，从候选题目中选择最合适的一道题。

## 难度系数说明（最重要）
- 难度系数通常在 0~1：**数值越小越难**。
- 参考区间（就近归类即可）：
  - 0.00~0.39：困难
  - 0.40~0.69：中等
  - 0.70~1.00：简单
- 例子：0.30=困难，0.65=中等，0.85=简单。

## 选题要求
{requirement}

## 候选题目（共{len(questions)}道）
{questions_text}

## 选择规则（按优先级）
1. 先满足难度要求（最重要）。
2. 再匹配题型、知识点、其他约束。
3. 题干要完整可用：尽量避免“需登录/无题干/公式占位/解析缺失”等问题。
4. 若无完全匹配，选择最接近的，并在 reason 中说明差距。

## 输出格式（严格 JSON）
```json
{{
  "selected_index": 1,
  "selected_question_id": "题目ID",
  "reason": "选择这道题的理由（必须说明难度匹配情况）",
  "analysis": "对各题目的简要对比（重点说明难度区间与匹配情况）"
}}
```

注意：
- selected_index 从 1 开始。
- difficulty 缺失时，请基于题干内容自行判断难度，并说明依据。
- 题干中的[公式:<svg...>]是数学公式的SVG图形，请识别其中的数学符号。
"""

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
