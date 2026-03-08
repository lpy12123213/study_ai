"""
子AI选题服务 - 从候选题目中选择最符合要求的题目
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

from backend.core import llm_console
from backend.core.settings import (
    CHAT_PROVIDER,
    SUB_AI_TIMEOUT,
    SUB_MODEL,
    SUB_MODEL_MAX_TOKENS,
    SUB_MODEL_TEMPERATURE,
    settings,
)


def _infer_provider_for_model(model: str) -> str:
    m = (model or "").strip()
    ml = m.lower()
    moonshot_like = (
        ml.startswith("moonshotai/")
        or ml.startswith("moonshot/")
        or ml.startswith("kimi-")
        or ml.startswith("moonshot-")
    )
    if moonshot_like and (settings.moonshot_api_key or "").strip():
        return "moonshot"
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

    if getattr(settings, "llm_provider_pinned", False):
        provider = str(settings.chat_provider or "").strip().lower() or "openai_compat"
        base_url = (settings.chat_base_url or "").rstrip("/")
        api_key = (settings.chat_api_key or "").strip()
    else:
        provider = _infer_provider_for_model(effective_model)
        if provider == "fireworks":
            base_url = (settings.fireworks_base_url or "").rstrip("/")
            api_key = (settings.fireworks_api_key or "").strip()
        elif provider == "moonshot":
            base_url = (settings.moonshot_base_url or "").rstrip("/")
            api_key = (settings.moonshot_api_key or "").strip()
        else:
            base_url = (settings.openrouter_base_url or "").rstrip("/")
            api_key = (settings.openrouter_api_key or "").strip()

    if not api_key:
        return {"success": False, "error": f"未配置 {provider} API Key（当前模型: {effective_model}）"}

    normalized_model = effective_model
    if provider == "moonshot" and "/" in normalized_model:
        normalized_model = normalized_model.split("/")[-1]

    effective_temperature = float(SUB_MODEL_TEMPERATURE)
    if provider == "moonshot" and normalized_model.lower().startswith("kimi-"):
        effective_temperature = 1.0

    req_id = f"subai-{uuid.uuid4().hex[:8]}"
    start_ts = llm_console.log_start(
        req_id=req_id,
        provider=provider,
        model=normalized_model,
        stream=False,
        temperature=effective_temperature,
        max_tokens=int(SUB_MODEL_MAX_TOKENS),
        base_url=base_url,
    )
    finish_reason = ""
    usage: Dict[str, Any] = {}
    content_chars = 0
    err = ""

    def _elapsed_s() -> float:
        if not start_ts:
            return 0.0
        try:
            return max(0.0, time.time() - float(start_ts))
        except Exception:
            return 0.0

    # 构建题目描述文本
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

    # 构建完整的 prompt（尽量短、明确，避免对子模型造成理解偏差）
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
                    "model": normalized_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": effective_temperature,
                    "max_tokens": SUB_MODEL_MAX_TOKENS,
                },
            )

            if response.status_code != 200:
                err = f"http_status_{response.status_code}"
                return {
                    "success": False,
                    "error": f"API调用失败: {response.status_code}",
                    "response_text": response.text[:500],
                }

            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            try:
                choice0 = data.get("choices", [{}])[0] if isinstance(data, dict) else {}
                finish_reason = str(choice0.get("finish_reason") or "")
            except Exception:
                finish_reason = ""
            if isinstance(data, dict) and isinstance(data.get("usage"), dict):
                usage = dict(data.get("usage") or {})
            if isinstance(content, str) and content:
                content_chars = len(content)
                llm_console.log_delta(req_id=req_id, channel="content", text=content)

            # 解析JSON响应
            try:
                import re

                json_match = re.search(r"\{[\s\S]*\}", content)
                if json_match:
                    result = json.loads(json_match.group())

                    # 验证并补充信息（容错：selected_index 可能为 null / 非数字）
                    question_ids = [str(q.get("question_id", "")).strip() for q in questions]
                    id_to_index = {qid: idx for idx, qid in enumerate(question_ids) if qid}

                    selected_question_id_raw = result.get("selected_question_id")
                    selected_question_id = (
                        str(selected_question_id_raw).strip() if selected_question_id_raw is not None else ""
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
                    err = "parse_error_no_json"
                    return {"success": False, "error": "无法解析AI响应", "raw_response": content[:500]}
            except json.JSONDecodeError as e:
                err = f"json_decode_error: {e}"
                return {"success": False, "error": f"JSON解析失败: {str(e)}", "raw_response": content[:500]}

    except httpx.TimeoutException:
        err = "timeout"
        return {"success": False, "error": "请求超时"}
    except Exception as e:
        err = str(e)
        return {"success": False, "error": f"请求错误: {str(e)}"}
    finally:
        llm_console.log_end(
            req_id=req_id,
            elapsed_s=_elapsed_s(),
            finish_reason=finish_reason,
            usage=usage,
            content_chars=content_chars,
            error=err,
        )
