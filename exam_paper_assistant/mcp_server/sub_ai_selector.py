"""
子AI选题服务 - 从候选题目中选择最符合要求的题目
"""

from __future__ import annotations

import json
import httpx
from typing import List, Dict, Any, Optional

from core.settings import (
    CHAT_PROVIDER,
    settings,
    SUB_AI_TIMEOUT,
    SUB_MODEL,
    SUB_MODEL_MAX_TOKENS,
    SUB_MODEL_TEMPERATURE,
)

def _infer_provider_for_model(model: str) -> str:
    m = (model or "").strip()
    if m.startswith("accounts/"):
        return "fireworks"
    if "/" in m:
        return "openrouter"
    return CHAT_PROVIDER


async def select_best_question(
    questions: List[Dict[str, Any]],
    requirement: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用子AI从候选题目中选择最符合要求的一道

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
    provider = _infer_provider_for_model(effective_model)
    if provider == "fireworks":
        base_url = (settings.fireworks_base_url or "").rstrip("/")
        api_key = (settings.fireworks_api_key or "").strip()
    else:
        base_url = (settings.openrouter_base_url or "").rstrip("/")
        api_key = (settings.openrouter_api_key or "").strip()

    if not api_key:
        return {"success": False, "error": f"未配置 {provider} API Key（当前模型: {effective_model}）"}

    # 构建题目描述文本
    questions_text = ""
    for i, q in enumerate(questions, 1):
        stem = q.get('stem', '')
        if not stem:
            stem = "(无题干内容)"

        questions_text += f"""
【题目{i}】
- ID: {q.get('question_id', 'N/A')}
- 题型: {q.get('type', '未知')}
- 难度系数: {q.get('difficulty', '未知')}
- 知识点: {q.get('knowledge_points', '未知')}
- 题干内容: {stem}
"""

    # 构建完整的 prompt
    prompt = f"""你是一个专业的选题助手。请根据以下要求，从候选题目中选择最合适的一道题。

## ⚠️ 重要提示（必须严格遵守）
- **难度系数越低越难**：困难题（难度系数小）< 中等题 < 简单题（难度系数大）
- 如果要求选择"困难"或"较难"题目，**必须优先**选择难度系数较小的题
- 如果要求选择"简单"或"容易"题目，**必须优先**选择难度系数较大的题
- **难度要求是首要条件**，即使其他方面稍差也要满足难度要求
- 如果没有给出难度系数, 请自行判断题目的难度，并在分析中说明理由

## 选题要求
{requirement}

## 候选题目（共{len(questions)}道）
{questions_text}

## 任务
1. **首先检查难度**：根据要求筛选符合难度条件的题目
2. 在符合难度的题目中，分析知识点、题型等其他要求
3. 选择最符合要求的一道题
4. 说明选择理由（必须说明难度是否符合）

## 输出格式（严格JSON）
```json
{{
    "selected_index": 1,
    "selected_question_id": "题目ID",
    "reason": "选择这道题的理由（必须说明难度匹配情况）",
    "analysis": "对各题目的简要分析（重点说明难度）"
}}
```

注意：
- selected_index 是题目序号（从1开始）
- **难度匹配是最重要的选择标准**
- 如果没有完全符合难度要求的题目，选择最接近的并在reason中明确说明
- 题干中的[公式:<svg...>]是数学公式的SVG图形，请识别其中的数学符号
"""

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if provider == "openrouter":
            headers["HTTP-Referer"] = "http://localhost:8000"
            headers["X-Title"] = "Exam Paper Assistant - Sub AI"

        async with httpx.AsyncClient(timeout=SUB_AI_TIMEOUT) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json={
                    "model": effective_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": SUB_MODEL_TEMPERATURE,
                    "max_tokens": SUB_MODEL_MAX_TOKENS
                }
            )

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"API调用失败: {response.status_code}",
                    "response_text": response.text[:500]
                }

            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            # 解析JSON响应
            try:
                import re
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    result = json.loads(json_match.group())

                    # 验证并补充信息（容错：selected_index 可能为 null / 非数字）
                    question_ids = [str(q.get("question_id", "")).strip() for q in questions]
                    id_to_index = {qid: idx for idx, qid in enumerate(question_ids) if qid}

                    selected_question_id_raw = result.get("selected_question_id")
                    selected_question_id = (
                        str(selected_question_id_raw).strip()
                        if selected_question_id_raw is not None
                        else ""
                    )

                    selected_idx: int
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

                    # Normalize fields for callers
                    result["selected_index"] = selected_idx + 1
                    if selected_question_id:
                        result["selected_question_id"] = selected_question_id

                    result["success"] = True
                    return result
                else:
                    return {
                        "success": False,
                        "error": "无法解析AI响应",
                        "raw_response": content[:500]
                    }
            except json.JSONDecodeError as e:
                return {
                    "success": False,
                    "error": f"JSON解析失败: {str(e)}",
                    "raw_response": content[:500]
                }

    except httpx.TimeoutException:
        return {"success": False, "error": "请求超时"}
    except Exception as e:
        return {"success": False, "error": f"请求错误: {str(e)}"}
