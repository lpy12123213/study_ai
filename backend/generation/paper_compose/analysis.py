import asyncio
import os
from typing import Any, Dict, List

from backend.core.logging_utils import get_logger
from backend.core.settings import settings
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry
from backend.llm.runner import run_text

logger = get_logger(__name__)


def _analysis_comment_user_prompt(
    *,
    paper_name: str,
    q_count: int,
    type_info: str,
    diff_info: str,
    difficulty: float,
    diff_str: str,
) -> str:
    return create_default_prompt_registry().render(
        "paper_compose.analysis_comment.user.v1",
        paper_name=paper_name,
        q_count=q_count,
        type_info=type_info or "未知",
        diff_info=diff_info,
        difficulty=difficulty,
        diff_str=diff_str,
    ).content


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

    model = str(os.getenv("PAPER_ANALYSIS_MODEL") or settings.main_model or "").strip() or "openai/gpt-4o-mini"

    # 如果没有 API key，使用模板生成
    if not is_llm_configured(scope="chat"):
        return _fallback_comment(paper_name, q_count, diff_str, type_info)

    prompt = _analysis_comment_user_prompt(
        paper_name=paper_name,
        q_count=q_count,
        type_info=type_info,
        diff_info=diff_info,
        difficulty=difficulty,
        diff_str=diff_str,
    )

    async def _call_llm() -> str:
        return await run_text(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.7,
            max_tokens=300,
            stream=False,
            raise_on_fail=False,
            retries=2,
            timeout_s=30.0,
            req_id_prefix="paper-comment",
            scope="chat",
        )

    try:
        # `analyze_paper(...)` is invoked via `run_in_executor(...)`, so this
        # normally runs in a non-async thread and `asyncio.run(...)` is safe.
        try:
            asyncio.get_running_loop()
            # If called from an async context by accident, fall back to the template
            # to avoid `asyncio.run` crashes.
            return _fallback_comment(paper_name, q_count, diff_str, type_info)
        except RuntimeError:
            content = asyncio.run(_call_llm()).strip()

        return content or _fallback_comment(paper_name, q_count, diff_str, type_info)
    except Exception as exc:
        logger.exception("AI comment generation failed", extra={"error": str(exc)})
        return _fallback_comment(paper_name, q_count, diff_str, type_info)


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
