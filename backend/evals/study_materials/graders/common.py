"""评分器公共类型与维度分值配置。

所有 grader 都是纯函数：输入用例 + 事件流/成稿，输出 ``DimensionResult``。
最终质量维度集中在 ``DIMENSION_MAX``；实现过程诊断使用独立的
``PROCESS_DIMENSION_MAX``，不再把某一种代理编排方式当成用户价值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# 最终质量维度 → 满分。总和必须为 100。
DIMENSION_MAX: Dict[str, float] = {
    "R": 10.0,  # 多步检索过程
    "K": 35.0,  # 知识理解（事实点受"可溯源"门控，见 knowledge.py）
    "L": 20.0,  # 学习闭环（目标、例题、自测、答案/评分点）
    "F": 15.0,  # 结构与格式
    "A": 5.0,  # 美观与可读性
    "C": 15.0,  # 引用与学术规范
}

# 过程诊断不进入百分制总分。子代理是一种实现策略，而不是成稿质量本身。
PROCESS_DIMENSION_MAX: Dict[str, float] = {"S": 15.0}

DIMENSION_TITLES: Dict[str, str] = {
    "R": "多步检索过程",
    "K": "知识理解",
    "L": "学习闭环",
    "S": "子代理使用",
    "F": "结构与格式",
    "A": "美观与可读性",
    "C": "引用与学术规范",
    # W 是 LLM rubric 写作诊断：独立字段展示，不在 DIMENSION_MAX/PROCESS_DIMENSION_MAX 中计分。
    "W": "写作 rubric（LLM 诊断）",
}


@dataclass
class CheckResult:
    id: str
    description: str
    score: float
    max_score: float
    detail: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "score": round(self.score, 2),
            "max_score": round(self.max_score, 2),
            "detail": self.detail,
            "metrics": self.metrics,
        }


@dataclass
class DimensionResult:
    dimension: str
    title: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def score(self) -> float:
        return sum(c.score for c in self.checks)

    @property
    def max_score(self) -> float:
        return sum(c.max_score for c in self.checks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "title": self.title,
            "score": round(self.score, 2),
            "max_score": round(self.max_score, 2),
            "checks": [c.to_dict() for c in self.checks],
        }


def make_dimension(key: str) -> DimensionResult:
    return DimensionResult(dimension=key, title=DIMENSION_TITLES.get(key, key))


def validate_weights() -> None:
    total = sum(DIMENSION_MAX.values())
    if abs(total - 100.0) > 1e-6:
        raise ValueError(f"DIMENSION_MAX 总和必须为 100，当前 {total}")
