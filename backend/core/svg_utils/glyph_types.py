"""Dataclasses + LaTeX operator constants used by the SVG → LaTeX pipeline.

Pulled out of the (very long) ``svg_to_latex.py`` so the type definitions live
in one focused place and can be imported without dragging in the entire
parsing module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Glyph:
    """字形数据结构。

    Each glyph corresponds to a single ``<path>`` element in the source SVG;
    the per-glyph ``signature`` is an MD5-prefix used for character lookup.
    """

    x: float
    y: float
    width: float
    height: float
    path_d: str
    signature: str
    char: Optional[str] = None
    is_fraction_line: bool = False  # 是否为分数线
    scale_x: float = 1.0
    scale_y: float = 1.0

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    @property
    def is_horizontal_line(self) -> bool:
        """检测是否为水平线（可能是分数线）。"""
        return self.width > self.height * 3 and self.height < 3


@dataclass
class FractionBar:
    """分数线数据结构。"""

    x1: float
    x2: float
    y: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2


@dataclass
class FormulaStructure:
    """公式结构。"""

    type: str  # 'simple', 'fraction', 'sqrt', 'superscript', 'subscript'
    content: str
    children: List["FormulaStructure"] = field(default_factory=list)


@dataclass
class SqrtRegion:
    """根号区域数据结构。"""

    x1: float  # 根号覆盖的起始 x
    x2: float  # 根号覆盖的结束 x
    y_top: float  # 根号顶部 y 坐标
    y_bottom: float  # 根号底部 y 坐标
    sqrt_glyph: Optional[Glyph] = None  # 根号符号本身

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2


@dataclass
class CasesRegion:
    """方程组（大括号）区域数据结构。"""

    x: float
    y_top: float
    y_bottom: float
    brace_glyph: Glyph
    rows: List[List[Glyph]] = field(default_factory=list)


# 大型运算符列表（需要上下限的符号）
LARGE_OPERATORS = frozenset(
    {
        "\\sum",
        "\\prod",
        "\\int",
        "\\oint",
        "\\iint",
        "\\iiint",
        "\\bigcup",
        "\\bigcap",
        "\\bigsqcup",
        "\\bigvee",
        "\\bigwedge",
        "\\coprod",
        "\\lim",
        "\\max",
        "\\min",
        "\\sup",
        "\\inf",
        "\\limsup",
        "\\liminf",
        "\\varlimsup",
        "\\varliminf",
    }
)

# 需要下标而非上下限的运算符（如 lim）
SUBSCRIPT_ONLY_OPERATORS = frozenset(
    {
        "\\lim",
        "\\max",
        "\\min",
        "\\sup",
        "\\inf",
        "\\limsup",
        "\\liminf",
    }
)


__all__ = [
    "CasesRegion",
    "FormulaStructure",
    "FractionBar",
    "Glyph",
    "LARGE_OPERATORS",
    "SUBSCRIPT_ONLY_OPERATORS",
    "SqrtRegion",
]
