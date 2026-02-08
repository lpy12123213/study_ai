from typing import List, Dict, Any
import os
import httpx
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


def calculate_difficulty_score(questions: List[Dict[str, Any]]) -> float:
    """
    计算试卷难度系数 (0-1, 1为最难)
    """
    if not questions:
        return 0.5

    score_map = {
        "简单": 0.3,
        "中等": 0.6,
        "困难": 0.9,
        "": 0.5
    }

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

    data = [
        {"subject": k, "A": v, "fullMark": len(questions)}
        for k, v in type_counts.items()
    ]

    # 如果数据太少，基于试卷名称推断一些能力维度
    if len(data) < 3:
        base_topics = ["计算能力", "逻辑推理", "综合应用"]
        for i, topic in enumerate(base_topics):
            if len(data) >= 5:
                break
            data.append({
                "subject": topic,
                "A": max(1, len(questions) // (i + 2)),
                "fullMark": len(questions)
            })

    return data


def generate_ai_comment(paper_name: str, difficulty: float, questions: List[Dict[str, Any]]) -> str:
    """
    使用 OpenRouter API 生成 AI 评语
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

    # 如果没有API key，使用模板生成
    if not OPENROUTER_API_KEY:
        return _fallback_comment(paper_name, q_count, diff_str, type_info)

    prompt = f"""你是一位专业的教育评估专家。请根据以下试卷信息，生成一段简洁专业的试卷分析评语（100-150字）：

试卷名称：{paper_name}
题目数量：{q_count}道
题型分布：{type_info or "未知"}
难度分布：{diff_info}
综合难度系数：{difficulty}（满分1.0）
难度评级：{diff_str}

请从试卷结构、难度分布、适用对象、答题建议等方面进行简要分析。语言要专业但易懂。"""

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                OPENROUTER_BASE_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "Exam Paper Assistant"
                },
                json={
                    "model": "x-ai/grok-4.1-fast:free",
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 300,
                    "temperature": 0.7
                }
            )

            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
            else:
                print(f"OpenRouter API error: {response.status_code} - {response.text}")
                return _fallback_comment(paper_name, q_count, diff_str, type_info)

    except Exception as e:
        print(f"AI comment generation failed: {e}")
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

    return {
        "difficulty_score": difficulty,
        "radar_data": radar_data,
        "ai_comment": comment
    }
