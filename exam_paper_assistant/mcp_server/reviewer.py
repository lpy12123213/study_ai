"""
审卷人服务 - 使用 AI 对试卷/题目进行审查
支持 OpenRouter 和 Fireworks AI
"""

from __future__ import annotations

import json
import httpx
from typing import List, Dict, Any

from core.settings import (
    FIREWORKS_API_KEY,
    FIREWORKS_BASE_URL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    REVIEW_HTTP_REFERER,
    REVIEW_MAX_STEM_CHARS,
    REVIEW_MODEL,
    REVIEW_MODEL_MAX_TOKENS,
    REVIEW_MODEL_TEMPERATURE,
    REVIEW_PROVIDER,
    REVIEW_TIMEOUT,
    REVIEW_X_TITLE,
)

# Compatibility aliases (old local variable names in this file).
REVIEW_TEMPERATURE = REVIEW_MODEL_TEMPERATURE
REVIEW_MAX_TOKENS = REVIEW_MODEL_MAX_TOKENS


def _get_api_config() -> Dict[str, Any]:
    """根据 REVIEW_PROVIDER 获取 API 配置"""
    if REVIEW_PROVIDER == "fireworks":
        return {
            "api_key": FIREWORKS_API_KEY,
            "base_url": FIREWORKS_BASE_URL,
            "provider": "fireworks",
            "model": REVIEW_MODEL if REVIEW_MODEL.startswith("accounts/") else f"accounts/fireworks/models/{REVIEW_MODEL}"
        }
    else:  # openrouter
        return {
            "api_key": OPENROUTER_API_KEY,
            "base_url": OPENROUTER_BASE_URL,
            "provider": "openrouter",
            "model": REVIEW_MODEL
        }


async def review_questions_with_openrouter(
    questions: List[Dict[str, Any]],
    paper_name: str = "",
    subject: str = "",
    focus: str = "",
    strictness: int = 3,
) -> Dict[str, Any]:
    """
    使用 AI 对试卷/题目进行审查（支持 OpenRouter 和 Fireworks AI）

    Args:
        questions: 题目列表，每个题目包含 question_id, stem, type, difficulty, knowledge_points 等
        paper_name: 试卷名称（可选）
        subject: 学科名称（可选）
        focus: 审查重点（可选，如：是否超纲、难度是否均衡、题干规范性等）
        strictness: 严格度 1-5（越高越苛刻）

    Returns:
        {
            "success": True/False,
            "review": "审查意见文本",
            "provider": "使用的API供应商",
            "model": "使用的模型"
        }
    """
    api_config = _get_api_config()

    if not api_config["api_key"]:
        provider_name = "FIREWORKS_API_KEY" if REVIEW_PROVIDER == "fireworks" else "OPENROUTER_API_KEY"
        return {
            "success": False,
            "error": f"未配置 {provider_name}，请在 .env 文件中设置"
        }

    if not questions:
        return {"success": False, "error": "没有题目可供审查"}

    # 构建题目描述文本
    questions_text = ""
    for i, q in enumerate(questions, 1):
        stem = q.get("stem", "")
        if not stem:
            stem = "(无题干内容)"

        # 截断过长的题干
        if len(stem) > REVIEW_MAX_STEM_CHARS:
            stem = stem[:REVIEW_MAX_STEM_CHARS] + "..."

        questions_text += f"""
【第{i}题】
- ID: {q.get('question_id', 'N/A')}
- 题型: {q.get('type', '未知')}
- 难度系数: {q.get('difficulty', '未知')}
- 知识点: {q.get('knowledge_points', '未知')}
- 题干: {stem}
"""

    # 严格度描述
    strictness_desc = {
        1: "宽松（只指出明显错误）",
        2: "较宽松（指出错误和较大问题）",
        3: "适中（指出错误、问题和改进建议）",
        4: "较严格（细致审查，提出优化意见）",
        5: "非常严格（从考试命题专家角度全面审查）"
    }.get(strictness, "适中")

    # 构建 prompt
    focus_text = ""
    if focus:
        focus_text = f"""
## 🎯 用户特别要求（优先关注）
**{focus}**
请在审查时重点关注上述用户要求，并在报告开头首先回应这一诉求。
"""
    paper_info = f"试卷名称: {paper_name}\n" if paper_name else ""
    subject_info = f"学科: {subject}\n" if subject else ""

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
审查严格度: {strictness}/5 ({strictness_desc})
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

示例格式：
---
## 审查报告

### 总体评价
整体质量评分: X/10
...

### 题干规范性
...

### 难度分布分析
...

### 知识点覆盖
...

### 发现的问题
1. ...
2. ...

### 改进建议
1. ...
2. ...
---
"""

    try:
        # 构建请求头
        headers = {
            "Authorization": f"Bearer {api_config['api_key']}",
            "Content-Type": "application/json",
        }
        # OpenRouter 需要额外的头
        if api_config["provider"] == "openrouter":
            headers["HTTP-Referer"] = REVIEW_HTTP_REFERER
            headers["X-Title"] = REVIEW_X_TITLE

        async with httpx.AsyncClient(timeout=REVIEW_TIMEOUT) as client:
            response = await client.post(
                f"{api_config['base_url']}/chat/completions",
                headers=headers,
                json={
                    "model": api_config["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": REVIEW_TEMPERATURE,
                    "max_tokens": REVIEW_MAX_TOKENS
                }
            )

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"API调用失败: {response.status_code}",
                    "provider": api_config["provider"],
                    "response_text": response.text[:500]
                }

            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            if not content:
                return {
                    "success": False,
                    "error": "AI 返回空内容",
                    "provider": api_config["provider"]
                }

            # 返回审查结果
            return {
                "success": True,
                "review": content,
                "provider": api_config["provider"],
                "model": api_config["model"],
                "strictness": strictness,
                "questions_reviewed": len(questions)
            }

    except httpx.TimeoutException:
        return {"success": False, "error": f"请求超时（{REVIEW_TIMEOUT}秒）", "provider": api_config["provider"]}
    except Exception as e:
        return {"success": False, "error": f"请求错误: {str(e)}", "provider": api_config["provider"]}
