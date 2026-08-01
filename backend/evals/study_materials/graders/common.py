"""评分器公共类型与维度分值配置。

所有 grader 都是纯函数：输入用例 + 事件流/成稿，输出 ``DimensionResult``。
维度分值集中在 ``DIMENSION_MAX``，调难度只动这一个表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# 维度 → 满分。总和必须为 100；校准基线时先调这里。
# 权重向当前系统的结构性缺口（子代理、引用、溯源知识）倾斜：
# 这三块合计 63 分，默认 ReAct 路径在前两块上天然为 0。
DIMENSION_MAX: Dict[str, float] = {
    "R": 15.0,  # 多步检索过程
    "K": 35.0,  # 知识理解（事实点受"可溯源"门控，见 knowledge.py）
    "S": 15.0,  # 子代理使用
    "F": 12.0,  # 结构与格式
    "A": 10.0,  # 美观与可读性
    "C": 13.0,  # 引用与学术规范
}

DIMENSION_TITLES: Dict[str, str] = {
    "R": "多步检索过程",
    "K": "知识理解",
    "S": "子代理使用",
    "F": "结构与格式",
    "A": "美观与可读性",
    "C": "引用与学术规范",
}


@dataclass
class CheckResult:
    id: str
    description: str
    score: float
    max_score: float
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "score": round(self.score, 2),
            "max_score": round(self.max_score, 2),
            "detail": self.detail,
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
