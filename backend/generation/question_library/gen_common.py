from __future__ import annotations

import random
from typing import List

from backend.core.settings import LESSON_PLAN_TEMPERATURE
from backend.generation.question_library.subject_knowledge import get_subject_bank

DEFAULT_SEARCH_CONFIG = {
    "preset": "balanced-creative",
    "depth": 4,
    "beam_width": 12,
    "expand_budget": 140,
    "skill_branch_factor": 4,
    "reasoning_branch_factor": 4,
    "trap_branch_factor": 3,
    "surface_branch_factor": 3,
    "difficulty_match_weight": 0.24,
    "novelty_weight": 0.24,
    "skill_coverage_weight": 0.2,
    "solvability_weight": 0.2,
    "ambiguity_penalty": 0.26,
    "template_penalty": 0.16,
    "reference_alignment_weight": 0.12,
    "judge_pass_score": 70,
    "difficulty_tolerance": 0.22,
    "solver_consensus_n": 3,
    "max_repair_rounds": 2,
    # Only attempt a repair when the judge score is close to the pass floor.
    # Low-quality "template" questions should be discarded rather than rewritten.
    "repair_score_band": 20,
    "repair_min_score": 50,
    "answer_mismatch_penalty": 12,
    "ambiguity_penalty_score": 8,
    "judge_require_pass_flag": False,
    "realize_min_max_tokens": 50000,
    "drafts_per_spec": 3,
    # New: brainstorm stage (can be disabled by config override).
    "enable_brainstorm": True,
    "brainstorm_seed_count": 8,
}


_MATH_SEED_TAGS = [
    "参数变化",
    "分类讨论",
    "构造反例",
    "数形结合",
    "条件反推",
    "综合应用",
    "极限思想",
    "递推归纳",
    "对称性分析",
    "特殊化策略",
    "逆向思维",
    "整体代换",
    "降维处理",
    "边界分析",
    "等价变换",
]

_MATH_SKILLS = [
    "概念辨析",
    "性质判定",
    "计算推导",
    "条件反推",
    "参数讨论",
    "构造反例",
    "综合应用",
    "不等式放缩",
    "恒等变形",
    "数列递推",
    "向量运算",
    "导数分析",
    "三角变换",
    "坐标运算",
    "概率统计",
    "排列组合",
    "极坐标转换",
    "参数方程处理",
]

_MATH_REASONING_PATTERNS = [
    "参数变化分析 + 分类讨论",
    "构造函数/构造反例",
    "等价转化 + 多步推导",
    "数形结合 + 关键不等式",
    "反证法/归谬",
    "分离变量/配方法 + 结构化求解",
    "递推归纳 + 边界验证",
    "极限逼近 + 夹逼准则",
    "对称性利用 + 简化运算",
    "特殊值代入 + 猜想验证",
    "整体代换 + 降次处理",
    "逆向分析 + 条件倒推",
    "局部放缩 + 整体估计",
    "主元法 + 参数分离",
    "几何直观 + 代数验证",
    "递归构造 + 数学归纳",
]

_MATH_TRAPS = [
    "忽略定义域/取值范围",
    "边界点漏判",
    "把必要条件当充分条件",
    "符号讨论遗漏",
    "条件转化方向弄反",
    "极值/最值概念混淆",
    "等号成立条件遗漏",
    "隐含条件未挖掘",
    "周期性/对称性忽略",
    "单调性区间端点错误",
    "渐近线遗漏",
    "复数运算实虚部混淆",
    "向量共线条件遗漏",
    "概率事件独立性误判",
    "数列首项特殊性忽略",
    "导数符号变化点漏判",
]

_MATH_SURFACES = [
    "参数变化探究题",
    "带约束的综合解答题",
    "反例辨析题",
    "分类讨论压轴题",
    "几何意义转化题",
    "开放性探究题",
    "存在性/恒成立问题",
    "多变量优化题",
    "递推数列综合题",
    "函数与导数压轴题",
    "解析几何轨迹题",
    "立体几何证明题",
    "概率分布综合题",
    "三角函数综合题",
    "向量几何综合题",
    "数列不等式证明题",
]


def _is_math_subject(subject: str) -> bool:
    s = str(subject or "").strip()
    return "数学" in s or s.lower() in {"math", "mathematics"}


def get_seed_tags(subject: str) -> List[str]:
    """Subject-aware seed tags used by root spec seeding."""

    bank = get_subject_bank(str(subject or "").strip())
    return [str(x).strip() for x in (bank.seed_tags or []) if str(x or "").strip()]


def get_skills(subject: str) -> List[str]:
    bank = get_subject_bank(str(subject or "").strip())
    return [str(x).strip() for x in (bank.skills or []) if str(x or "").strip()]


def get_reasoning_patterns(subject: str) -> List[str]:
    bank = get_subject_bank(str(subject or "").strip())
    return [str(x).strip() for x in (bank.reasoning_patterns or []) if str(x or "").strip()]


def get_traps(subject: str) -> List[str]:
    bank = get_subject_bank(str(subject or "").strip())
    return [str(x).strip() for x in (bank.traps or []) if str(x or "").strip()]


def get_surfaces(subject: str) -> List[str]:
    bank = get_subject_bank(str(subject or "").strip())
    return [str(x).strip() for x in (bank.surfaces or []) if str(x or "").strip()]


def _clip_unique(options: List[str], n: int) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for it in options or []:
        t = str(it or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= n:
            break
    return out


def _sample_unique(options: List[str], n: int) -> List[str]:
    deduped = _clip_unique(options, len(options or []))
    if not deduped:
        return []
    random.shuffle(deduped)
    return deduped[: max(1, int(n or 1))]


def _difficulty_rank(value: str) -> float:
    text = str(value or "").strip()
    if any(token in text for token in ["基础", "较易", "偏易", "简单", "易"]):
        return 0.0
    if any(token in text for token in ["中等", "适中"]):
        return 1.0
    if any(token in text for token in ["较难", "偏难", "困难", "压轴", "难"]):
        return 2.0
    return 1.0


def _difficulty_variants(target: str, n: int) -> List[str]:
    target_text = str(target or "").strip()
    rank = _difficulty_rank(target_text)
    total = max(1, int(n or 1))
    if rank <= 0.0:
        pool = ["基础", "简单", "简单", "中等", "简单"]
    elif rank >= 2.0:
        pool = ["偏难", "困难", "困难", "中等偏难", "困难"]
    else:
        pool = ["中等", "中等", "偏易", "偏难", "中等"]
    out: List[str] = []
    for index in range(total):
        out.append(pool[index % len(pool)])
    return out


def _difficulty_instruction(difficulty: str) -> str:
    rank = _difficulty_rank(difficulty)
    if rank <= 0.0:
        return "优先生成基础题，注重概念理解与基本方法，避免拔高为中高难综合题。"
    if rank >= 2.0:
        return "优先生成高难度题，注重思维深度、综合性与区分度，避免退化为基础套路题。"
    return "优先生成中等难度题，注重方法运用、常见变式和适度区分度。"


def _resolve_realize_temperature(difficulty: str) -> float:
    """Temperature cap that scales with target difficulty (looser for harder problems)."""
    base = float(LESSON_PLAN_TEMPERATURE)
    rank = _difficulty_rank(difficulty)
    if rank <= 0.0:
        cap = 0.4
    elif rank >= 2.0:
        cap = 0.7
    else:
        cap = 0.55
    return max(0.1, min(cap, base if base > 0 else cap))
