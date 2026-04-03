import os
import time
import uuid
from typing import Any, Dict, List

import httpx

from backend.llm import console as llm_console
from backend.core.logging_utils import get_logger
from backend.core.settings import settings

logger = get_logger(__name__)


def _chat_headers(*, provider: str, api_key: str) -> Dict[str, str]:
    headers: Dict[str, str] = {
        "Authorization": f"Bearer {str(api_key or '').strip()}",
        "Content-Type": "application/json",
    }
    if str(provider or "").strip().lower() == "openrouter":
        if (settings.review_http_referer or "").strip():
            headers["HTTP-Referer"] = settings.review_http_referer
        if (settings.review_x_title or "").strip():
            headers["X-Title"] = settings.review_x_title
    return headers


def calculate_difficulty_score(questions: List[Dict[str, Any]]) -> float:
    """
    计算试卷难度系数 (0-1, 1为最难)
    """
    if not questions:
        return 0.5

    score_map = {"简单": 0.3, "中等": 0.6, "困难": 0.9, "": 0.5}

    total_score = sum(score_map.get(q.get("difficulty") or "", 0.5) for q in questions)
    return round(total_score / len(questions), 2)


def generate_knowledge_distribution(questions: List[Dict[str, Any]], paper_name: str) -> List[Dict[str, Any]]:
    """
    生成知识点分布 (Radar Chart Data)
    """
    type_counts = {}
    for q in questions:
        q_type = q.get("type") or "其他"
        type_counts[q_type] = type_counts.get(q_type, 0) + 1

    data = [{"subject": k, "A": v, "fullMark": len(questions)} for k, v in type_counts.items()]

    # 如果数据太少，基于试卷名称推断一些能力维度
    if len(data) < 3:
        base_topics = ["计算能力", "逻辑推理", "综合应用"]
        for i, topic in enumerate(base_topics):
            if len(data) >= 5:
                break
            data.append({"subject": topic, "A": max(1, len(questions) // (i + 2)), "fullMark": len(questions)})

    return data


def generate_ai_comment(paper_name: str, difficulty: float, questions: List[Dict[str, Any]]) -> str:
    """
    使用 OpenAI-compatible Chat Completions API 生成 AI 评语。
    """
    q_count = len(questions)
    diff_str = "简单" if difficulty < 0.4 else "中等" if difficulty < 0.7 else "困难"

    # 统计题型分布
    type_stats = {}
    diff_stats = {"简单": 0, "中等": 0, "困难": 0, "未知": 0}
    for q in questions:
        q_type = q.get("type") or "未分类"
        type_stats[q_type] = type_stats.get(q_type, 0) + 1
        q_diff = q.get("difficulty") or "未知"
        if q_diff in diff_stats:
            diff_stats[q_diff] += 1
        else:
            diff_stats["未知"] += 1

    type_info = "、".join([f"{k}{v}道" for k, v in type_stats.items() if v > 0])
    diff_info = "、".join([f"{k}{v}道" for k, v in diff_stats.items() if v > 0])

    provider = str(settings.chat_provider or "").strip().lower()
    base_url = str(settings.chat_base_url or "").strip().rstrip("/")
    api_key = settings.chat_api_key.get_secret_value().strip()
    model = str(os.getenv("PAPER_ANALYSIS_MODEL") or settings.main_model or "").strip() or "openai/gpt-4o-mini"

    # 如果没有 API key，使用模板生成
    if not api_key or not base_url:
        return _fallback_comment(paper_name, q_count, diff_str, type_info)

    prompt = f"""你是一位专业的教育评估专家。请根据以下试卷信息，生成一段简洁专业的试卷分析评语（100-150字）：

试卷名称：{paper_name}
题目数量：{q_count}道
题型分布：{type_info or "未知"}
难度分布：{diff_info}
综合难度系数：{difficulty}（满分1.0）
难度评级：{diff_str}

请从试卷结构、难度分布、适用对象、答题建议等方面进行简要分析。语言要专业但易懂。"""

    req_id = f"paper-comment-{uuid.uuid4().hex[:8]}"
    start_ts = llm_console.log_start(
        req_id=req_id,
        provider=provider or "openai_compat",
        model=model,
        stream=False,
        temperature=0.7,
        max_tokens=300,
        base_url=base_url,
    )
    finish_reason = ""
    usage: Dict[str, Any] = {}
    content_chars = 0
    err = ""

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers=_chat_headers(provider=provider, api_key=api_key),
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 300,
                    "temperature": 0.7,
                },
            )

            if response.status_code == 200:
                data = response.json()
                try:
                    choice0 = data.get("choices", [{}])[0] if isinstance(data, dict) else {}
                    finish_reason = str(choice0.get("finish_reason") or "")
                except Exception:
                    finish_reason = ""
                if isinstance(data, dict) and isinstance(data.get("usage"), dict):
                    usage = dict(data.get("usage") or {})
                content = ""
                try:
                    content = str(data["choices"][0]["message"]["content"] or "").strip()
                except Exception:
                    content = ""
                if content:
                    content_chars = len(content)
                    llm_console.log_delta(req_id=req_id, channel="content", text=content)
                return content or _fallback_comment(paper_name, q_count, diff_str, type_info)
            else:
                err = f"http_status_{response.status_code}"
                logger.warning(
                    "OpenRouter API error",
                    extra={"status_code": int(response.status_code), "body_preview": str(response.text or "")[:800]},
                )
                return _fallback_comment(paper_name, q_count, diff_str, type_info)

    except Exception as e:
        err = str(e)
        logger.exception("AI comment generation failed", extra={"error": str(e)})
        return _fallback_comment(paper_name, q_count, diff_str, type_info)
    finally:
        elapsed_s = 0.0
        try:
            elapsed_s = max(0.0, time.time() - float(start_ts)) if start_ts else 0.0
        except Exception:
            elapsed_s = 0.0
        llm_console.log_end(
            req_id=req_id,
            elapsed_s=elapsed_s,
            finish_reason=finish_reason,
            usage=usage,
            content_chars=content_chars,
            error=err,
        )


def _fallback_comment(paper_name: str, q_count: int, diff_str: str, type_info: str) -> str:
    """备用模板评语"""
    base = f"这份《{paper_name}》试卷包含{q_count}道题目，整体难度为【{diff_str}】。"

    if type_info:
        base += f"题型包括{type_info}。"

    if diff_str == "简单":
        base += "试卷侧重基础知识巩固，适合用于日常练习或入门检测。"
    elif diff_str == "中等":
        base += "难度适中，兼顾基础与提高，适合阶段性测验使用。"
    else:
        base += "试卷具有较高挑战性，适合培优训练或考前冲刺。"

    base += f"建议答题时间控制在{q_count * 3}分钟左右。"
    return base


def analyze_paper(paper_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    主分析入口
    """
    questions = paper_data.get("questions", [])
    paper_name = paper_data.get("paper_name", "未命名试卷")

    difficulty = calculate_difficulty_score(questions)
    radar_data = generate_knowledge_distribution(questions, paper_name)
    comment = generate_ai_comment(paper_name, difficulty, questions)

    return {"difficulty_score": difficulty, "radar_data": radar_data, "ai_comment": comment}
