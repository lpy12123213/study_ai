"""
SVG公式转LaTeX工具（增强版）
使用字形签名精确匹配（非OCR/非AI）

原理：
1. 解析SVG，提取每个字形的位置和path数据
2. 计算每个path的MD5签名
3. 使用预定义的签名映射表将签名转换为字符
4. 根据位置关系识别上下标、分数、根号等结构
5. 组合成完整的LaTeX表达式

增强功能：
- 支持分数结构识别（通过检测水平分数线）
- 支持根号结构识别
- 支持括号匹配
- 自动学习新签名
- 可视化签名分析
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from backend.core.logging_utils import get_logger

try:
    import httpx
except ImportError:
    httpx = None

_SVG_LATEX_CACHE_MAX = 2048
_SVG_LATEX_CACHE: "OrderedDict[tuple[str, bool], tuple[str, tuple[str, ...]]]" = OrderedDict()

logger = get_logger(__name__)


def _svg_latex_cache_get(svg_url: str, use_advanced: bool) -> Optional[Tuple[str, List[str]]]:
    key = (svg_url, use_advanced)
    cached = _SVG_LATEX_CACHE.get(key)
    if not cached:
        return None
    _SVG_LATEX_CACHE.move_to_end(key)
    latex, unknown = cached
    return latex, list(unknown)


def _svg_latex_cache_set(svg_url: str, use_advanced: bool, latex: str, unknown: List[str]) -> None:
    key = (svg_url, use_advanced)
    _SVG_LATEX_CACHE[key] = (latex, tuple(unknown))
    _SVG_LATEX_CACHE.move_to_end(key)
    while len(_SVG_LATEX_CACHE) > _SVG_LATEX_CACHE_MAX:
        _SVG_LATEX_CACHE.popitem(last=False)


@dataclass
class Glyph:
    """字形数据结构"""

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
        """检测是否为水平线（可能是分数线）"""
        return self.width > self.height * 3 and self.height < 3


@dataclass
class FractionBar:
    """分数线数据结构"""

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
    """公式结构"""

    type: str  # 'simple', 'fraction', 'sqrt', 'superscript', 'subscript'
    content: str
    children: List["FormulaStructure"] = field(default_factory=list)


@dataclass
class SqrtRegion:
    """根号区域数据结构"""

    x1: float  # 根号覆盖的起始x
    x2: float  # 根号覆盖的结束x
    y_top: float  # 根号顶部y坐标
    y_bottom: float  # 根号底部y坐标
    sqrt_glyph: Optional[Glyph] = None  # 根号符号本身

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2


@dataclass
class CasesRegion:
    """方程组（大括号）区域数据结构"""

    x: float
    y_top: float
    y_bottom: float
    brace_glyph: Glyph
    rows: List[List[Glyph]] = field(default_factory=list)


# 大型运算符列表（需要上下限的符号）
LARGE_OPERATORS = {
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

# 需要下标而非上下限的运算符（如 lim）
SUBSCRIPT_ONLY_OPERATORS = {
    "\\lim",
    "\\max",
    "\\min",
    "\\sup",
    "\\inf",
    "\\limsup",
    "\\liminf",
}


def update_large_op_signatures():
    """从签名映射中更新大型运算符签名集合"""
    global LARGE_OP_SIGNATURES
    LARGE_OP_SIGNATURES = set()
    for sig, char in GLYPH_SIGNATURES.items():
        if char in LARGE_OPERATORS:
            LARGE_OP_SIGNATURES.add(sig)


# 大型运算符的 LaTeX 签名映射（用于识别这些符号）
LARGE_OP_SIGNATURES: Set[str] = set()

# ============================================================================
# 模糊签名映射（可能有歧义的字符）
# 某些签名在不同上下文中可能表示不同字符
# ============================================================================
AMBIGUOUS_SIGNATURES: Dict[str, Dict[str, str]] = {
    # D签名问题：在运算符上下文中可能是减号
    # "c36b3f1d": {
    #     "default": "D",
    #     "operator_context": "-",
    # },
}

# 可以作为操作数的字符（用于上下文判断）
OPERAND_CHARS = set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
OPERAND_CHARS.update({"\\pi", "\\alpha", "\\beta", "\\gamma", "\\theta", "\\phi"})

# 运算符字符
OPERATOR_CHARS = set("+-*/=<>")
OPERATOR_CHARS.update({"\\times", "\\div", "\\cdot", "\\pm", "\\mp", "\\leq", "\\geq", "\\neq"})


# ============================================================================
# 字形签名映射表（path MD5前8位 -> LaTeX字符）
# 通过分析组卷网SVG公式收集
# 注意：此处仅为默认值，实际签名从 glyph_signatures.json 加载
# ============================================================================
GLYPH_SIGNATURES: Dict[str, str] = {
    # === 数字 ===
    "b9716cb9": "2",
    "5f32a7e2": "4",
    "3b2fdd74": "1",
    "b673824f": "0",
    "0896fac2": "3",
    "5a9f14b0": "5",
    "71e8b9a1": "6",
    "96aeade1": "1",
    # === 小写字母 ===
    "cf58f988": "x",
    "6cb4ef65": "y",
    "2aa7df06": "o",
    "9fe3b8c9": "0",
    "f9e514d2": "c",
    "56274f04": "a",
    "34f7c565": ",",
    "803c545f": "h",
    "d3af06b5": "i",
    "ee57931a": "j",
    "099c8924": "b",
    "2273560c": "l",
    "b65ef479": "m",
    "e1096052": "m",
    "396a708d": "p",
    "9b58691c": "q",
    "7dd54be2": "r",
    "cd4e58fc": "s",
    "97e16f2e": "t",
    "cc0ab61a": "u",
    "1d0fc683": "v",
    "2fd59755": "w",
    "b1fb51b4": "z",
    # === 大写字母 ===
    "ee8570c5": "P",
    "d7198a8e": "O",
    "fd61fc79": "A",
    "c5232a6d": "B",
    "db65bd2f": "C",
    "c36b3f1d": "D",
    "da16791e": "E",
    "8637303d": "F",
    "7c7bb518": "G",
    "9315853a": "H",
    "10fb4c81": "I",
    "d45c14ff": "J",
    "e407c344": "K",
    # === 运算符 ===
    "7cbdeebe": "-",
    "e113c1a7": "+",
    "a1040187": "=",
    "aecc1ab6": "<",
    "3a890ca6": ">",
    # === 特殊符号 ===
    "8c6104df": ":",
    "cadf428a": "\\sqrt",
    "dfeccf59": "\\perp",
    "b6caebbe": "\\angle",
}

# 签名数据文件路径
SIGNATURES_FILE = os.path.join(os.path.dirname(__file__), "glyph_signatures.json")

# 全局缓存
_signatures_loaded = False


def load_signatures() -> Dict[str, str]:
    """加载保存的签名映射"""
    global _signatures_loaded
    if _signatures_loaded:
        return GLYPH_SIGNATURES

    if os.path.exists(SIGNATURES_FILE):
        try:
            with open(SIGNATURES_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                # 过滤掉注释项（以_comment开头的键）
                for key, value in saved.items():
                    if not key.startswith("_comment"):
                        GLYPH_SIGNATURES[key] = value
        except Exception:
            logger.debug("svg_signatures_load_failed", extra={"path": SIGNATURES_FILE}, exc_info=True)

    # 更新大型运算符签名集合
    update_large_op_signatures()

    _signatures_loaded = True
    return GLYPH_SIGNATURES


def save_signatures():
    """保存签名映射到文件"""
    try:
        with open(SIGNATURES_FILE, "w", encoding="utf-8") as f:
            json.dump(GLYPH_SIGNATURES, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("failed to save glyph signatures", extra={"error": str(e)})


def add_signature(signature: str, latex_char: str):
    """添加新的签名映射"""
    GLYPH_SIGNATURES[signature] = latex_char
    save_signatures()


def add_signatures_batch(mappings: Dict[str, str]):
    """批量添加签名映射"""
    GLYPH_SIGNATURES.update(mappings)
    save_signatures()


def is_operand_char(char: Optional[str]) -> bool:
    """检查字符是否为操作数（数字、字母、常量等）"""
    if not char:
        return False
    # 去除未知签名标记
    if char.startswith("[?") and char.endswith("]"):
        return False
    return char in OPERAND_CHARS or char.isalnum()


def resolve_ambiguous_char(
    glyph: "Glyph", prev_glyph: Optional["Glyph"] = None, next_glyph: Optional["Glyph"] = None
) -> str:
    """
    根据上下文解析可能有歧义的字符

    用于解决如 D 签名在某些上下文中可能是减号的问题

    Args:
        glyph: 当前字形
        prev_glyph: 前一个字形
        next_glyph: 后一个字形

    Returns:
        解析后的字符
    """
    sig = glyph.signature

    # 如果没有在模糊签名表中，直接返回原字符
    if sig not in AMBIGUOUS_SIGNATURES:
        return glyph.char

    ambig = AMBIGUOUS_SIGNATURES[sig]
    default_char = ambig.get("default", glyph.char)

    # 检查是否在运算符上下文中
    # 规则：如果前后都是操作数，则可能是运算符
    prev_is_operand = prev_glyph and is_operand_char(prev_glyph.char)
    next_is_operand = next_glyph and is_operand_char(next_glyph.char)

    if prev_is_operand and next_is_operand:
        # 在操作数之间，可能是运算符
        return ambig.get("operator_context", default_char)

    # 检查位置关系：如果字符很窄且在两个操作数之间居中，更可能是运算符
    if prev_glyph and next_glyph:
        gap_to_prev = glyph.x - (prev_glyph.x + prev_glyph.width)
        gap_to_next = next_glyph.x - (glyph.x + glyph.width)

        # 如果前后间隙相近，说明在中间位置，可能是运算符
        if abs(gap_to_prev - gap_to_next) < 5 and glyph.width < 10:
            return ambig.get("operator_context", default_char)

    return default_char


# ============================================================================
# LaTeX 输出后处理：修复常见歧义与格式问题
# ============================================================================

_GEOMETRY_HINT_TOKENS = (
    "\\perp",
    "\\angle",
    "\\triangle",
    "\\odot",
    "\\parallel",
)


def _is_geometry_like_latex(latex: str) -> bool:
    """
    粗略判断 LaTeX 是否更像几何题中的“点/线段/角”标记，而非代数表达式。

    仅用于启用更激进的 `0->O`、`i->I` 等替换规则，避免误伤复数/三角函数等场景。
    """
    if not latex:
        return False

    if any(tok in latex for tok in _GEOMETRY_HINT_TOKENS):
        return True

    # 典型点/线段写法：O3、OP、A1、0P、03、Ph 等（注意排除 LaTeX 命令的反斜杠）
    # - 0 后跟字母/数字（排除 0.5 之类的小数）
    # - 大写字母后跟字母/数字（点名/线段名）
    # - 数字后跟大写字母（如 A1、B2 变体）
    score = 0
    zero_point = bool(re.search(r"(?<![0-9\\])0(?=[1-9A-Za-z])", latex))
    score += 1 if zero_point else 0
    score += len(re.findall(r"(?<!\\)[A-Z](?=[0-9A-Za-z])", latex))
    score += len(re.findall(r"(?<![0-9\\])[0-9](?=[A-Z])", latex))
    # 数字 + 单独的 i（点 I 常被误识别为 i；避免误伤 sin/lim 等：要求 i 后面不是小写字母）
    # - 若同式里出现了 “0 + 字母/数字” 的点名特征（如 03、0P），则更倾向为几何，
    #   放宽对 i 前一个字符的限制（允许 ...35i 这类点名）。
    if zero_point:
        score += len(re.findall(r"[0-9](?=i(?![a-z]))", latex))
    else:
        score += len(re.findall(r"(?<![a-z0-9\\])[0-9](?=i(?![a-z]))", latex))

    # 两处及以上“点名式相邻字符”基本可视为几何上下文（如 03=0i=6 或 035i）
    return score >= 2


_COMMANDS_NEED_SPACE = (
    "odot",
    "sin",
    "cos",
    "tan",
    "cot",
    "sec",
    "csc",
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "theta",
    "lambda",
    "mu",
    "pi",
    "rho",
    "sigma",
    "phi",
    "omega",
    "perp",
    "angle",
    "triangle",
    "times",
    "cdot",
    "pm",
    "mp",
    "leq",
    "geq",
    "neq",
    "parallel",
)
_COMMAND_NEEDS_SPACE_RE = re.compile(r"(\\(?:" + "|".join(_COMMANDS_NEED_SPACE) + r"))(?=[A-Za-z])")


def postprocess_latex(latex: str) -> str:
    """
    对转换后的 LaTeX 做轻量后处理：
    - 将 `\\sqrt3` / `\\sqrtc` 等补全为 `\\sqrt{3}` / `\\sqrt{c}`，避免与后续字符粘连
    - 将形似角符号的 `lABC` 修正为 `\\angle ABC`（输出为 `\\angleABC`）
    - 修正 `Oo:` 这类标签中的 `o/0` 歧义
    - 在几何上下文中修正 `0/O`、`i/I` 等常见歧义
    """
    if not latex:
        return latex

    # 1) \sqrt 的单字符参数补全：\sqrt3 -> \sqrt{3}，\sqrt[?xxxx] -> \sqrt{[?xxxx]}
    latex = re.sub(
        r"\\sqrt\s*(?!\{)(\[\?[0-9a-f]{8}\]|[A-Za-z0-9])",
        r"\\sqrt{\1}",
        latex,
    )

    # 2) 角：lABC / l35I -> \angleABC（只在 l 后跟 3 个字母数字时触发，避免误伤 ln/lim）
    latex = re.sub(
        r"(?<![A-Za-z\\])l(?=[A-Za-z0-9]{3})",
        r"\\angle",
        latex,
    )

    # 3) O0 标签：Oo: -> O0:（仅在大写字母后、且后面紧跟 :/大写/数字/_/} 时触发）
    latex = re.sub(
        r"(?<=[A-Z])o(?=[:A-Z0-9_\\}])",
        "0",
        latex,
    )

    # 4) 几何上下文：0->O、i->I（避免误伤 sin/lim 等由多个小写字母组成的函数名）
    if _is_geometry_like_latex(latex):
        # 0 作为点 O：03/0P/0i -> O3/OP/OI
        latex = re.sub(r"(?<![0-9\\])0(?=[1-9A-Za-z])", "O", latex)
        # P0（点 O）这类：P0\perp... -> PO\perp...（排除 O0 这种索引式写法）
        latex = re.sub(r"(?<=[A-NP-Z])0(?=[^0-9A-Za-z]|$)", "O", latex)
        latex = re.sub(r"(?<![a-z\\])i(?![a-z])", "I", latex)

    # 5) 常见 LaTeX 命令与后续字母分隔：
    #    例如 \sinx -> \sin x，\odotO -> \odot O（避免被 TeX 解析为更长的未知命令）。
    latex = _COMMAND_NEEDS_SPACE_RE.sub(r"\1 ", latex)

    return latex


def is_sqrt_signature(sig: str) -> bool:
    """检查签名是否对应根号符号"""
    char = GLYPH_SIGNATURES.get(sig, "")
    return char == "\\sqrt"


def detect_sqrt_regions(
    glyphs: List["Glyph"], svg_lines: List[Tuple[float, float, float, float]]
) -> List["SqrtRegion"]:
    """
    检测 SVG 中的根号区域

    根号通常由以下元素组成：
    1. 根号符号本身 (\\sqrt 签名)
    2. 斜线（根号的左侧部分）
    3. 水平线（根号顶部覆盖内容的横线）

    Args:
        glyphs: 字形列表
        svg_lines: SVG 中的线段列表 [(x1, y1, x2, y2), ...]

    Returns:
        根号区域列表
    """
    sqrt_regions = []

    # 方法1：通过根号符号签名检测
    sqrt_glyphs = [g for g in glyphs if is_sqrt_signature(g.signature)]

    for sqrt_g in sqrt_glyphs:
        # 找到根号符号右侧的水平线
        sqrt_y = sqrt_g.y

        # 查找可能的根号顶部水平线
        for x1, y1, x2, y2 in svg_lines:
            is_horizontal = abs(y1 - y2) < 2
            # 水平线应该在根号符号附近或右侧
            if is_horizontal and x1 >= sqrt_g.x - 5:
                # 检查y坐标是否接近根号顶部
                if abs(y1 - sqrt_y) < 20:
                    sqrt_regions.append(
                        SqrtRegion(x1=x1, x2=x2, y_top=y1, y_bottom=sqrt_g.y + sqrt_g.height, sqrt_glyph=sqrt_g)
                    )
                    break

    # 方法2：通过线段组合检测（斜线+水平线的组合）
    # 找到所有斜线（非水平、非垂直）
    for i, (x1, y1, x2, y2) in enumerate(svg_lines):
        is_horizontal = abs(y1 - y2) < 2
        is_vertical = abs(x1 - x2) < 2

        if is_horizontal or is_vertical:
            continue

        # 这是一条斜线，检查是否有水平线与其右端点相连
        # 根号的斜线通常向右上倾斜
        if x2 > x1 and y2 < y1:  # 右上方向
            for j, (ox1, oy1, ox2, oy2) in enumerate(svg_lines):
                if i == j:
                    continue
                other_horizontal = abs(oy1 - oy2) < 2
                if other_horizontal:
                    # 检查水平线左端点是否与斜线右端点相连（容差5像素）
                    if abs(x2 - ox1) < 10 and abs(y2 - oy1) < 10:
                        # 找到一个根号结构
                        # 但需要检查这个是否已经被方法1检测到
                        already_detected = any(abs(sr.x1 - ox1) < 5 and abs(sr.x2 - ox2) < 5 for sr in sqrt_regions)
                        if not already_detected:
                            sqrt_regions.append(
                                SqrtRegion(
                                    x1=ox1,
                                    x2=ox2,
                                    y_top=oy1,
                                    y_bottom=max(y1, oy1) + 20,  # 估算底部
                                    sqrt_glyph=None,
                                )
                            )
                        break

    return sqrt_regions


def is_brace_signature(sig: str) -> bool:
    """检查签名是否对应左大括号"""
    char = GLYPH_SIGNATURES.get(sig, "")
    return char == "\\{" or sig == "65d6c9b1" or sig == "ac8466ff"


def detect_cases_regions(glyphs: List[Glyph]) -> List[CasesRegion]:
    """检测方程组（大括号）区域"""
    cases_regions = []

    # Sort glyphs by x to process left-to-right
    sorted_glyphs = sorted(glyphs, key=lambda g: g.x)

    for g in sorted_glyphs:
        # Check if it's a brace
        is_brace = is_brace_signature(g.signature)
        if not is_brace:
            # Heuristic for unknown braces: tall and narrow
            if g.height > 30 and g.width < g.height / 4:
                is_brace = True

        if is_brace:
            y_top = g.y
            y_bottom = g.y + g.height

            # Find glyphs inside this region
            inner_glyphs = []
            for other in glyphs:
                if other == g:
                    continue
                # Check if it's generally to the right and within y-bounds
                if other.x > g.x - 5 and other.y >= y_top - 5 and other.y <= y_bottom + 5:
                    if other.center_x > g.center_x:
                        inner_glyphs.append(other)

            if inner_glyphs:
                # Group into rows
                inner_glyphs.sort(key=lambda ig: ig.y)
                rows = []
                current_row = []
                if inner_glyphs:
                    current_row.append(inner_glyphs[0])
                    current_y = inner_glyphs[0].y

                    for ig in inner_glyphs[1:]:
                        # Threshold for row separation
                        if abs(ig.y - current_y) < 12:
                            current_row.append(ig)
                        else:
                            rows.append(current_row)
                            current_row = [ig]
                            current_y = ig.y
                    rows.append(current_row)

                cases_regions.append(CasesRegion(x=g.x, y_top=y_top, y_bottom=y_bottom, brace_glyph=g, rows=rows))

    return cases_regions


def compute_path_signature(path_d: str) -> str:
    """计算path的MD5签名（前8位）"""
    return hashlib.md5(path_d.encode()).hexdigest()[:8]


def estimate_glyph_bounds(path_d: str) -> Tuple[float, float]:
    """估算字形的宽度和高度（从path数据）"""
    # 提取所有数值
    numbers = re.findall(r"-?\d+\.?\d*", path_d)
    if len(numbers) < 4:
        return 10.0, 10.0

    floats = [float(n) for n in numbers]
    # 简单估算：取最大最小值差
    xs = floats[::2] if len(floats) > 1 else [0]
    ys = floats[1::2] if len(floats) > 1 else [0]

    width = max(xs) - min(xs) if xs else 10.0
    height = max(ys) - min(ys) if ys else 10.0

    return max(width, 1.0), max(height, 1.0)


def parse_svg_glyphs(
    svg_content: str,
) -> Tuple[List[Glyph], List[FractionBar], List[Tuple[float, float, float, float]]]:
    """
    解析SVG，提取每个字形的信息、分数线和所有线段

    支持多种SVG格式：
    1. <g transform="translate(x,y)"><path d="..."/></g>
    2. <use transform="translate(x,y)" xlink:href="#..."/>
    3. 直接的<path d="..."/>
    4. 嵌套的g元素（用于分数等复杂结构）
    5. <line>元素（分数线、根号线等）

    Returns:
        (字形列表, 分数线列表, 所有线段列表 [(x1, y1, x2, y2), ...])
    """
    glyphs = []
    fraction_bars = []
    load_signatures()

    # 检测<line>元素（分数线）- 使用更灵活的匹配
    line_elements = re.findall(r"<line([^>]*)/?>", svg_content)
    all_lines = []  # 存储所有线段信息

    for line_attrs in line_elements:
        try:
            x1_match = re.search(r'x1="([^"]+)"', line_attrs)
            x2_match = re.search(r'x2="([^"]+)"', line_attrs)
            y1_match = re.search(r'y1="([^"]+)"', line_attrs)
            y2_match = re.search(r'y2="([^"]+)"', line_attrs)

            if all([x1_match, x2_match, y1_match, y2_match]):
                x1 = float(x1_match.group(1))
                x2 = float(x2_match.group(1))
                y1 = float(y1_match.group(1))
                y2 = float(y2_match.group(1))
                all_lines.append((x1, y1, x2, y2))
        except ValueError:
            continue

    # 识别根号符号的线段组合（斜线+水平线的组合）
    sqrt_horizontal_lines = set()  # 属于根号的水平线索引

    for i, (x1, y1, x2, y2) in enumerate(all_lines):
        is_horizontal = abs(y1 - y2) < 2
        if not is_horizontal:
            # 这是一条斜线，检查是否有水平线与其端点相连
            for j, (ox1, oy1, ox2, oy2) in enumerate(all_lines):
                if i == j:
                    continue
                other_horizontal = abs(oy1 - oy2) < 2
                if other_horizontal:
                    # 检查是否端点相连（容差5像素）
                    if (
                        (abs(x2 - ox1) < 5 and abs(y2 - oy1) < 5)
                        or (abs(x2 - ox2) < 5 and abs(y2 - oy2) < 5)
                        or (abs(x1 - ox1) < 5 and abs(y1 - oy1) < 5)
                        or (abs(x1 - ox2) < 5 and abs(y1 - oy2) < 5)
                    ):
                        sqrt_horizontal_lines.add(j)

    # 只将非根号的水平线作为分数线
    for i, (x1, y1, x2, y2) in enumerate(all_lines):
        if abs(y1 - y2) < 2 and i not in sqrt_horizontal_lines:
            # 额外检查：分数线通常有一定宽度（部分小分数如 1/3 的线很短）
            width = abs(x2 - x1)
            if width >= 5:
                fraction_bars.append(FractionBar(min(x1, x2), max(x1, x2), (y1 + y2) / 2))

    def parse_transform_robust(transform_str: str) -> Tuple[float, float, float, float]:
        """解析transform，返回 (tx, ty, sx, sy)"""
        tx, ty = 0.0, 0.0
        sx, sy = 1.0, 1.0

        t_match = re.search(r"translate\(([^)]+)\)", transform_str)
        if t_match:
            parts = [float(x.strip()) for x in t_match.group(1).split(",")]
            tx = parts[0]
            if len(parts) > 1:
                ty = parts[1]

        m_match = re.search(r"matrix\(([^)]+)\)", transform_str)
        if m_match:
            parts = [float(x.strip()) for x in m_match.group(1).split(",")]
            if len(parts) >= 4:
                sx = parts[0]
                sy = parts[3]
                if len(parts) >= 6:
                    tx += parts[4]
                    ty += parts[5]
        return tx, ty, sx, sy

    # 方式1：匹配带transform的g元素
    # 查找带有transform的g
    g_transform_pattern = r'<g[^>]*transform="([^"]+)"[^>]*>(.*?)</g>'
    g_matches = re.findall(g_transform_pattern, svg_content, re.DOTALL)

    for transform_str, inner_content in g_matches:
        try:
            tx, ty, sx, sy = parse_transform_robust(transform_str)
            path_matches = re.findall(r'<path[^>]*d="([^"]+)"', inner_content)
            for path_d in path_matches:
                sig = compute_path_signature(path_d)
                width, height = estimate_glyph_bounds(path_d)
                width *= sx
                height *= sy
                char = GLYPH_SIGNATURES.get(sig)
                glyphs.append(Glyph(tx, ty, width, height, path_d, sig, char, scale_x=sx, scale_y=sy))
        except ValueError:
            continue

    # 方式2：处理嵌套在stroke-width组中的路径（用于分数）
    # 查找带stroke-width的g元素（通常包含分数线和分数内容）
    stroke_g_pattern = r'<g[^>]*stroke-width="[^"]*"[^>]*>(.*?)</g>'
    stroke_matches = re.findall(stroke_g_pattern, svg_content, re.DOTALL)

    for inner in stroke_matches:
        # 在stroke组内查找所有path元素（更灵活的匹配）
        path_elements = re.findall(r"<path([^>]*)/?>", inner)
        for path_attrs in path_elements:
            # 提取d属性
            d_match = re.search(r'd="([^"]+)"', path_attrs)
            if not d_match:
                continue
            path_d = d_match.group(1)

            tx, ty, sx, sy = 0.0, 0.0, 1.0, 1.0

            # 提取transform属性（如果有）
            transform_match = re.search(r'transform="([^"]+)"', path_attrs)
            if transform_match:
                tx, ty, sx, sy = parse_transform_robust(transform_match.group(1))

            sig = compute_path_signature(path_d)
            width, height = estimate_glyph_bounds(path_d)

            width *= sx
            height *= sy

            char = GLYPH_SIGNATURES.get(sig)
            glyphs.append(Glyph(tx, ty, width, height, path_d, sig, char, scale_x=sx, scale_y=sy))

    # 去重（基于签名和位置）
    seen = set()
    unique_glyphs = []
    for g in glyphs:
        key = (round(g.x, 1), round(g.y, 1), g.signature)
        if key not in seen:
            seen.add(key)
            unique_glyphs.append(g)

    return unique_glyphs, fraction_bars, all_lines


def detect_fraction_lines(glyphs: List[Glyph]) -> List[Tuple[Glyph, List[Glyph], List[Glyph]]]:
    """
    检测分数结构

    返回: [(分数线字形, 分子字形列表, 分母字形列表), ...]
    """
    fractions = []

    # 找出可能的分数线（宽度大于高度的水平线）
    fraction_lines = [g for g in glyphs if g.is_horizontal_line]

    for line in fraction_lines:
        numerator = []  # 分子（在分数线上方）
        denominator = []  # 分母（在分数线下方）

        for g in glyphs:
            if g == line:
                continue

            # 检查是否在分数线的x范围内
            if g.x >= line.x - 5 and g.x <= line.x + line.width + 5:
                if g.y < line.y:  # 在分数线上方
                    numerator.append(g)
                elif g.y > line.y:  # 在分数线下方
                    denominator.append(g)

        if numerator or denominator:
            fractions.append((line, numerator, denominator))

    return fractions


def detect_superscripts_subscripts(
    glyphs: List[Glyph], baseline_y: float, y_threshold: float = 3.0
) -> Tuple[List[Glyph], List[Glyph], List[Glyph]]:
    """
    检测上标和下标

    返回: (基准线字形, 上标字形, 下标字形)
    """
    baseline_glyphs = []
    superscripts = []
    subscripts = []

    for g in glyphs:
        y_diff = g.y - baseline_y

        if y_diff < -y_threshold:
            superscripts.append(g)
        elif y_diff > y_threshold:
            subscripts.append(g)
        else:
            baseline_glyphs.append(g)

    return baseline_glyphs, superscripts, subscripts


def is_large_operator(char: Optional[str]) -> bool:
    """检查字符是否为大型运算符"""
    if not char:
        return False
    return char in LARGE_OPERATORS


def detect_large_operator_limits(
    glyphs: List[Glyph], operator_glyph: Glyph
) -> Tuple[List[Glyph], List[Glyph], List[Glyph]]:
    """
    检测大型运算符的上下限

    大型运算符（如∑、∫、∏）的上下限位于符号的正上方和正下方

    Returns:
        (剩余字形, 上限字形, 下限字形)
    """
    op_center_x = operator_glyph.center_x
    op_y = operator_glyph.y
    op_width = operator_glyph.width

    # 定义上下限的x范围（运算符中心附近）
    x_tolerance = max(op_width * 1.5, 10)

    upper_limit = []  # 上限（在运算符上方）
    lower_limit = []  # 下限（在运算符下方）
    remaining = []

    for g in glyphs:
        if g == operator_glyph:
            continue

        # 检查是否在运算符的x范围内（中心对齐）
        glyph_center_x = g.center_x
        if abs(glyph_center_x - op_center_x) <= x_tolerance:
            # 在运算符上方（y值更小，因为SVG坐标系y向下）
            if g.y < op_y - 3:
                upper_limit.append(g)
            # 在运算符下方
            elif g.y > op_y + operator_glyph.height + 3:
                lower_limit.append(g)
            else:
                remaining.append(g)
        else:
            remaining.append(g)

    return remaining, upper_limit, lower_limit


def format_large_operator(
    operator_char: str, upper_limit: List[Glyph], lower_limit: List[Glyph]
) -> Tuple[str, List[str]]:
    """
    格式化大型运算符及其上下限

    对于求和、积分等：\\sum_{下限}^{上限}
    对于极限等：\\lim_{下标}（通常没有上标）

    Returns:
        (LaTeX字符串, 未知签名列表)
    """
    unknown = []
    result = operator_char

    # 检查是否为只需要下标的运算符
    is_subscript_only = operator_char in SUBSCRIPT_ONLY_OPERATORS

    # 处理下限
    if lower_limit:
        lower_latex, lower_unknown = glyphs_to_latex(sorted(lower_limit, key=lambda g: g.x))
        unknown.extend(lower_unknown)
        result += "_{" + lower_latex + "}"

    # 处理上限（对于只需下标的运算符，上限可能是普通后续内容，不添加 ^ 符号）
    if upper_limit and not is_subscript_only:
        upper_latex, upper_unknown = glyphs_to_latex(sorted(upper_limit, key=lambda g: g.x))
        unknown.extend(upper_unknown)
        result += "^{" + upper_latex + "}"
    elif upper_limit and is_subscript_only:
        # 对于 lim 等，上方内容作为普通后续处理
        upper_latex, upper_unknown = glyphs_to_latex(sorted(upper_limit, key=lambda g: g.x))
        unknown.extend(upper_unknown)
        result += upper_latex

    return result, unknown


def glyphs_to_latex(glyphs: List[Glyph]) -> Tuple[str, List[str]]:
    """
    将字形列表转换为LaTeX字符串

    增强功能：
    - 智能检测上下标
    - 支持分数结构
    - 处理连续的上下标
    - 上下文感知识别（解决模糊字符如D/减号问题）

    Returns:
        (latex_string, unknown_signatures)
    """
    if not glyphs:
        return "", []

    # 按x坐标排序
    sorted_glyphs = sorted(glyphs, key=lambda g: g.x)

    # 找到基准y坐标（出现最多的y值）
    y_counts: Dict[float, int] = defaultdict(int)
    for g in sorted_glyphs:
        rounded_y = round(g.y, 0)
        y_counts[rounded_y] += 1
    baseline_y = max(y_counts, key=y_counts.get) if y_counts else 0

    result = []
    unknown = []
    current_mode = "normal"  # 'normal', 'superscript', 'subscript'

    for i, g in enumerate(sorted_glyphs):
        # 上下文感知识别：获取前后字形
        prev_glyph = sorted_glyphs[i - 1] if i > 0 else None
        next_glyph = sorted_glyphs[i + 1] if i < len(sorted_glyphs) - 1 else None

        # 优先使用字形的字符，如果有模糊签名则解析
        char = g.char

        if char is None:
            unknown.append(g.signature)
            char = f"[?{g.signature}]"
        elif g.signature in AMBIGUOUS_SIGNATURES:
            # 使用上下文感知解析
            char = resolve_ambiguous_char(g, prev_glyph, next_glyph)

        # 检测上下标（基于与基准y的偏移）
        y_diff = g.y - baseline_y

        # 确定当前字符的模式
        if y_diff < -2:
            new_mode = "superscript"
        elif y_diff > 2:
            new_mode = "subscript"
        else:
            new_mode = "normal"

        # 处理模式切换
        if new_mode != current_mode:
            # 关闭之前的模式
            if current_mode == "superscript":
                result.append("}")
            elif current_mode == "subscript":
                result.append("}")

            # 开启新模式
            if new_mode == "superscript":
                result.append("^{")
            elif new_mode == "subscript":
                result.append("_{")

            current_mode = new_mode

        result.append(char)

    # 关闭未闭合的括号
    if current_mode in ("superscript", "subscript"):
        result.append("}")

    return "".join(result), unknown


def glyphs_to_latex_advanced(
    glyphs: List[Glyph],
    fraction_bars: List[FractionBar] = None,
    svg_lines: List[Tuple[float, float, float, float]] = None,
) -> Tuple[str, List[str]]:
    """
    高级转换：支持分数、大型运算符、根号等复杂结构

    支持的结构:
    - 分数 \\frac{}{}
    - 大型运算符上下限 \\sum_{下限}^{上限}
    - 积分上下限 \\int_{下限}^{上限}
    - 极限 \\lim_{下标}
    - 根号 \\sqrt{} （新增）
    - 嵌套结构（如根号下有分数）

    Returns:
        (latex_string, unknown_signatures)
    """
    if not glyphs:
        return "", []

    unknown = []
    fraction_bars = fraction_bars or []
    svg_lines = svg_lines or []
    used_glyphs: Set[int] = set()
    result_parts = []  # [(x_position, latex_string)]
    sqrt_parts: List[Tuple[float, float, float, float, str]] = []  # (x, x1, x2, y_anchor, latex)

    # 第-1步：检测方程组区域
    cases_regions = detect_cases_regions(glyphs)

    for cases_region in cases_regions:
        used_glyphs.add(id(cases_region.brace_glyph))

        row_latexs = []

        for row_glyphs in cases_region.rows:
            # Mark as used
            for g in row_glyphs:
                used_glyphs.add(id(g))

            # Recurse
            if not row_glyphs:
                continue
            min_x = min(g.x for g in row_glyphs)
            max_x = max(g.x + g.width for g in row_glyphs)
            min_y = min(g.y for g in row_glyphs)
            max_y = max(g.y + g.height for g in row_glyphs)

            row_bars = [
                b
                for b in fraction_bars
                if b.x1 >= min_x - 5 and b.x2 <= max_x + 5 and b.y >= min_y - 5 and b.y <= max_y + 5
            ]
            row_lines = [
                line
                for line in svg_lines
                if line[0] >= min_x - 5 and line[2] <= max_x + 5 and line[1] >= min_y - 5 and line[3] <= max_y + 5
            ]

            row_latex, row_unknown = glyphs_to_latex_advanced(row_glyphs, row_bars, row_lines)
            row_latexs.append(row_latex)
            unknown.extend(row_unknown)

        cases_latex = "\\begin{cases} " + " \\\\ ".join(row_latexs) + " \\end{cases}"
        result_parts.append((cases_region.x, cases_latex))

    # 第零步：检测根号区域
    sqrt_regions = detect_sqrt_regions(glyphs, svg_lines) if svg_lines else []

    # 处理根号结构
    for sqrt_region in sqrt_regions:
        # 标记根号符号本身为已使用
        if sqrt_region.sqrt_glyph:
            used_glyphs.add(id(sqrt_region.sqrt_glyph))

        # 找到根号覆盖范围内的字形
        sqrt_inner_glyphs = []
        for g in glyphs:
            if id(g) in used_glyphs:
                continue

            # 检查字形是否在根号覆盖范围内
            glyph_center_x = g.x + g.width / 2
            if sqrt_region.x1 <= glyph_center_x <= sqrt_region.x2:
                # 检查是否在根号顶线和底部之间（y坐标）
                # 注意：SVG坐标系y轴向下
                if g.y >= sqrt_region.y_top - 5:  # 在根号顶线下方
                    sqrt_inner_glyphs.append(g)
                    used_glyphs.add(id(g))

        if sqrt_inner_glyphs:
            # 检查根号内部是否有分数结构
            inner_fraction_bars = [bar for bar in fraction_bars if sqrt_region.x1 <= bar.center_x <= sqrt_region.x2]

            if inner_fraction_bars:
                # 根号内有分数，递归处理（不传递svg_lines避免重复检测根号）
                inner_latex, inner_unknown = glyphs_to_latex_advanced(
                    sqrt_inner_glyphs,
                    inner_fraction_bars,
                    [],  # 不传递svg_lines，避免无限递归
                )
            else:
                # 普通内容
                inner_latex, inner_unknown = glyphs_to_latex(sqrt_inner_glyphs)

            unknown.extend(inner_unknown)

            # 确定根号的x位置用于排序
            sqrt_x = sqrt_region.sqrt_glyph.x if sqrt_region.sqrt_glyph else sqrt_region.x1
            sqrt_y = min((g.y for g in sqrt_inner_glyphs), default=sqrt_region.y_top)
            sqrt_parts.append((sqrt_x, sqrt_region.x1, sqrt_region.x2, sqrt_y, f"\\sqrt{{{inner_latex}}}"))

    # 第一步：处理大型运算符及其上下限
    large_ops = [g for g in glyphs if is_large_operator(g.char) and id(g) not in used_glyphs]

    for op in large_ops:
        used_glyphs.add(id(op))

        # 检测上下限
        remaining, upper, lower = detect_large_operator_limits([g for g in glyphs if id(g) not in used_glyphs], op)

        # 标记已使用的字形
        for g in upper + lower:
            used_glyphs.add(id(g))

        # 格式化运算符
        op_latex, op_unknown = format_large_operator(op.char, upper, lower)
        unknown.extend(op_unknown)
        result_parts.append((op.x, op_latex))

    # 第二步：使用分数线信息构建分数（排除已处理的根号内分数）
    processed_fraction_bars = set()
    for sqrt_region in sqrt_regions:
        for bar in fraction_bars:
            if sqrt_region.x1 <= bar.center_x <= sqrt_region.x2:
                processed_fraction_bars.add(id(bar))

    remaining_fraction_bars = [bar for bar in fraction_bars if id(bar) not in processed_fraction_bars]
    consumed_sqrt_parts: Set[int] = set()

    if remaining_fraction_bars:

        def render_fraction_side(side_glyphs: List[Glyph], side_sqrts: List[Tuple[float, str]]) -> str:
            if not side_glyphs and not side_sqrts:
                return ""

            items: List[Tuple[float, str, object]] = []
            for g in side_glyphs:
                items.append((g.x, "glyph", g))
            for x, latex in side_sqrts:
                items.append((x, "latex", latex))

            items.sort(key=lambda t: t[0])

            out: List[str] = []
            pending: List[Glyph] = []

            for _, kind, obj in items:
                if kind == "glyph":
                    pending.append(obj)  # type: ignore[arg-type]
                    continue
                if pending:
                    chunk, chunk_unknown = glyphs_to_latex(pending)
                    unknown.extend(chunk_unknown)
                    out.append(chunk)
                    pending = []
                out.append(obj)  # type: ignore[arg-type]

            if pending:
                chunk, chunk_unknown = glyphs_to_latex(pending)
                unknown.extend(chunk_unknown)
                out.append(chunk)

            return "".join(out)

        for bar in sorted(remaining_fraction_bars, key=lambda b: b.x1):
            numerator = []  # 分子（在分数线上方）
            denominator = []  # 分母（在分数线下方）

            for g in glyphs:
                if id(g) in used_glyphs:
                    continue

                # 检查是否在分数线的x范围内（带一定容差）
                glyph_center_x = g.x + g.width / 2
                if bar.x1 - 5 <= glyph_center_x <= bar.x2 + 5:
                    if g.y < bar.y - 2:  # 在分数线上方
                        numerator.append(g)
                        used_glyphs.add(id(g))
                    elif g.y > bar.y + 2:  # 在分数线下方
                        denominator.append(g)
                        used_glyphs.add(id(g))

            if numerator or denominator:
                num_sqrts: List[Tuple[float, str]] = []
                den_sqrts: List[Tuple[float, str]] = []

                # 将已解析的根号结构按所在分子/分母归并进来（否则会被当作“独立项”输出）
                for idx, (sx, sx1, sx2, sy, s_latex) in enumerate(sqrt_parts):
                    if idx in consumed_sqrt_parts:
                        continue
                    # 根号覆盖范围与分数线x范围有重叠
                    if sx2 < bar.x1 - 5 or sx1 > bar.x2 + 5:
                        continue
                    if sy < bar.y - 2:
                        num_sqrts.append((sx, s_latex))
                        consumed_sqrt_parts.add(idx)
                    elif sy > bar.y + 2:
                        den_sqrts.append((sx, s_latex))
                        consumed_sqrt_parts.add(idx)

                num_latex = render_fraction_side(numerator, num_sqrts)
                den_latex = render_fraction_side(denominator, den_sqrts)

                result_parts.append((bar.center_x, f"\\frac{{{num_latex}}}{{{den_latex}}}"))

    # 将未被分数吸收的根号结构输出为普通项
    for idx, (sx, _, __, ___, s_latex) in enumerate(sqrt_parts):
        if idx not in consumed_sqrt_parts:
            result_parts.append((sx, s_latex))

    # 第三步：处理剩余的字形
    remaining = [g for g in glyphs if id(g) not in used_glyphs]
    if remaining:
        rem_latex, rem_unknown = glyphs_to_latex(remaining)
        unknown.extend(rem_unknown)

        # 计算剩余字形的平均x位置
        if remaining:
            avg_x = sum(g.x for g in remaining) / len(remaining)
            result_parts.append((avg_x, rem_latex))

    # 如果有任何处理结果，按x坐标排序并合并
    if result_parts:
        result_parts.sort(key=lambda x: x[0])
        return "".join(p[1] for p in result_parts), list(set(unknown))

    # 检测分数结构（通过水平线字形）
    fractions = detect_fraction_lines(glyphs)

    if fractions:
        # 有分数结构，需要特殊处理
        used_glyphs: Set[int] = set()
        result_parts = []

        for line, numerator, denominator in fractions:
            # 标记已使用的字形
            used_glyphs.add(id(line))
            for g in numerator + denominator:
                used_glyphs.add(id(g))

            # 转换分子
            num_latex, num_unknown = glyphs_to_latex(numerator)
            unknown.extend(num_unknown)

            # 转换分母
            den_latex, den_unknown = glyphs_to_latex(denominator)
            unknown.extend(den_unknown)

            result_parts.append((line.x, f"\\frac{{{num_latex}}}{{{den_latex}}}"))

        # 处理剩余的字形
        remaining = [g for g in glyphs if id(g) not in used_glyphs]
        if remaining:
            rem_latex, rem_unknown = glyphs_to_latex(remaining)
            unknown.extend(rem_unknown)
            # 按位置合并
            for g in remaining:
                result_parts.append((g.x, g.char or f"[?{g.signature}]"))

        # 按x坐标排序并合并
        result_parts.sort(key=lambda x: x[0])
        return "".join(p[1] for p in result_parts), list(set(unknown))

    # 无分数结构，使用基础转换
    return glyphs_to_latex(glyphs)


# ============================================================================
# 异步网络函数
# ============================================================================


async def svg_url_to_latex(
    svg_url: str,
    client=None,
    use_advanced: bool = False,
) -> Tuple[Optional[str], List[str]]:
    """
    将SVG公式URL转换为LaTeX

    Args:
        svg_url: SVG图片的URL
        client: httpx.AsyncClient实例
        use_advanced: 是否使用高级转换（支持分数等）

    Returns:
        (LaTeX字符串, 未知签名列表)
    """
    if httpx is None:
        raise ImportError("需要安装httpx: pip install httpx")

    load_signatures()

    cached = _svg_latex_cache_get(svg_url, use_advanced)
    if cached is not None:
        return cached

    owns_client = client is None
    if owns_client:
        client_kwargs = dict(
            timeout=30,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
        try:
            client = httpx.AsyncClient(http2=True, **client_kwargs)
        except ImportError:
            client = httpx.AsyncClient(**client_kwargs)

    try:
        resp = await client.get(svg_url)
        if resp.status_code != 200:
            return None, []

        svg_content = resp.text
        if use_advanced:
            latex, unknown = svg_content_to_latex_advanced(svg_content)
        else:
            latex, unknown = svg_content_to_latex(svg_content)
        if latex:
            _svg_latex_cache_set(svg_url, use_advanced, latex, unknown)
            return latex, unknown
        return None, unknown

    except Exception as e:
        logger.warning("failed to parse svg to latex", extra={"error": str(e), "svg_url": svg_url})
        return None, []
    finally:
        if owns_client:
            await client.aclose()


async def batch_svg_to_latex(
    svg_urls: List[str],
    concurrency: int = 5,
    client=None,
    use_advanced: bool = False,
) -> Dict[str, Tuple[str, List[str]]]:
    """
    批量将SVG公式转换为LaTeX

    Returns:
        {svg_url: (latex, unknown_sigs)}
    """
    if httpx is None:
        raise ImportError("需要安装httpx: pip install httpx")

    load_signatures()
    results = {}
    semaphore = asyncio.Semaphore(concurrency)

    remaining_urls: List[str] = []
    for url in svg_urls:
        cached = _svg_latex_cache_get(url, use_advanced)
        if cached is not None:
            latex, unknown = cached
            if latex:
                results[url] = (latex, unknown)
            continue
        remaining_urls.append(url)

    async def convert_one(url, http_client):
        async with semaphore:
            latex, unknown = await svg_url_to_latex(url, client=http_client, use_advanced=use_advanced)
            return url, latex, unknown

    async def run(http_client):
        tasks = [convert_one(url, http_client) for url in remaining_urls]
        for coro in asyncio.as_completed(tasks):
            url, latex, unknown = await coro
            if latex:
                results[url] = (latex, unknown)
        return results

    if client is not None:
        if not remaining_urls:
            return results
        return await run(client)

    if not remaining_urls:
        return results

    # 提高连接限制以支持高并发
    limits = httpx.Limits(
        max_connections=max(concurrency * 2, 60),
        max_keepalive_connections=max(concurrency * 2, 60),
    )
    # 减少超时时间，加快单个请求失败后的恢复
    client_kwargs = dict(timeout=15, limits=limits)
    try:
        http_client = httpx.AsyncClient(http2=True, **client_kwargs)
    except ImportError:
        http_client = httpx.AsyncClient(**client_kwargs)
    async with http_client:
        return await run(http_client)


# ============================================================================
# 同步便捷函数
# ============================================================================


def svg_content_to_latex(svg_content: str) -> Tuple[str, List[str]]:
    """同步转换SVG内容为LaTeX"""
    load_signatures()
    glyphs, fraction_bars, svg_lines = parse_svg_glyphs(svg_content)
    if not glyphs:
        return "", []
    latex, unknown = glyphs_to_latex(glyphs)
    return postprocess_latex(latex), unknown


def svg_content_to_latex_advanced(svg_content: str) -> Tuple[str, List[str]]:
    """同步转换SVG内容为LaTeX（高级版，支持分数和根号）"""
    load_signatures()
    glyphs, fraction_bars, svg_lines = parse_svg_glyphs(svg_content)
    if not glyphs:
        return "", []
    latex, unknown = glyphs_to_latex_advanced(glyphs, fraction_bars, svg_lines)
    return postprocess_latex(latex), unknown


def svg_file_to_latex(svg_path: str, use_advanced: bool = False) -> Tuple[Optional[str], List[str]]:
    """读取本地SVG文件并转换为LaTeX"""
    load_signatures()
    if not os.path.exists(svg_path):
        return None, []
    with open(svg_path, "r", encoding="utf-8") as f:
        content = f.read()
    if use_advanced:
        latex, unknown = svg_content_to_latex_advanced(content)
    else:
        latex, unknown = svg_content_to_latex(content)
    return (latex if latex else None), unknown


def quick_svg_to_latex(source: str, use_advanced: bool = False) -> Tuple[Optional[str], List[str]]:
    """
    便捷函数：自动识别输入类型并转换

    Args:
        source: URL、文件路径或原始SVG内容
        use_advanced: 是否使用高级转换

    Returns:
        (LaTeX字符串, 未知签名列表)
    """
    is_url = source.startswith("http://") or source.startswith("https://")
    looks_like_svg = "<svg" in source

    if looks_like_svg:
        if use_advanced:
            latex, unknown = svg_content_to_latex_advanced(source)
        else:
            latex, unknown = svg_content_to_latex(source)
        return (latex if latex else None), unknown

    if os.path.exists(source):
        return svg_file_to_latex(source, use_advanced)

    if is_url:
        return asyncio.run(svg_url_to_latex(source, use_advanced=use_advanced))

    raise ValueError("不支持的输入格式，请提供SVG URL、文件路径或原始SVG内容")


# ============================================================================
# HTML处理函数
# ============================================================================


def extract_formula_urls_from_html(html: str) -> List[str]:
    """从HTML中提取公式图片URL并转为SVG格式"""
    urls = re.findall(r'https://[^"\']+/formula/[^"\']+\.png', html)
    svg_urls = [url.replace(".png", ".svg") for url in urls]
    return list(set(svg_urls))


async def replace_formulas_with_latex(
    html: str,
    concurrency: int = 5,
    use_advanced: bool = False,
) -> Tuple[str, Dict[str, List[str]]]:
    """
    将HTML中的公式图片替换为LaTeX

    Returns:
        (替换后的文本, {url: unknown_sigs})
    """
    pattern = r'<img[^>]*src="(https://[^"]+/formula/[^"]+\.png)"[^>]*>'
    matches = list(set(re.findall(pattern, html)))

    if not matches:
        return html, {}

    svg_urls = [url.replace(".png", ".svg") for url in matches]
    latex_map = await batch_svg_to_latex(svg_urls, concurrency=concurrency, use_advanced=use_advanced)

    result = html
    all_unknown = {}

    for png_url in matches:
        svg_url = png_url.replace(".png", ".svg")
        if svg_url in latex_map:
            latex, unknown = latex_map[svg_url]
            if unknown:
                all_unknown[svg_url] = unknown
            # 用LaTeX替换img标签
            # 注意：替换字符串中的反斜杠需要转义，避免被re.sub解释为正则回引用
            img_pattern = f'<img[^>]*src="{re.escape(png_url)}"[^>]*>'
            latex_escaped = latex.replace("\\", "\\\\")
            result = re.sub(img_pattern, f"${latex_escaped}$", result)

    return result, all_unknown


# ============================================================================
# 签名学习和分析工具
# ============================================================================


def analyze_svg_for_learning(svg_content: str, known_latex: str = None):
    """
    分析SVG用于学习新的字形签名

    如果提供known_latex，可以尝试自动建立映射
    """
    glyphs, fraction_bars, svg_lines = parse_svg_glyphs(svg_content)

    print(f"发现 {len(glyphs)} 个字形:")
    for i, g in enumerate(sorted(glyphs, key=lambda g: g.x)):
        known = g.char or "未知"
        print(f"  {i}: x={g.x:>7.2f}, y={g.y:>7.2f}, sig={g.signature}, char={known}")

    if fraction_bars:
        print(f"\n发现 {len(fraction_bars)} 条分数线:")
        for bar in fraction_bars:
            print(f"  x1={bar.x1:.1f}, x2={bar.x2:.1f}, y={bar.y:.1f}")

    if known_latex:
        print(f"\n已知LaTeX: {known_latex}")
        print("请使用 add_signature('签名', 'LaTeX字符') 添加映射")


def collect_signatures_from_urls(svg_urls: List[str]) -> Dict[str, Dict]:
    """
    从多个SVG URL收集签名信息

    Returns:
        {signature: {'count': int, 'paths': [path_d, ...]}}
    """
    import urllib.request

    all_sigs = defaultdict(lambda: {"count": 0, "paths": []})

    for svg_url in svg_urls:
        try:
            with urllib.request.urlopen(svg_url, timeout=10) as resp:
                svg = resp.read().decode("utf-8")

            glyphs, _, _ = parse_svg_glyphs(svg)
            for g in glyphs:
                all_sigs[g.signature]["count"] += 1
                if len(all_sigs[g.signature]["paths"]) < 3:
                    all_sigs[g.signature]["paths"].append(g.path_d[:200])
        except Exception:
            logger.debug("svg_signature_fetch_failed", extra={"url": svg_url}, exc_info=True)

    return dict(all_sigs)


def generate_signature_analyzer_html(signatures: Dict[str, Dict], output_path: str, title: str = "字形签名分析器"):
    """
    生成可视化HTML页面用于分析和标注签名

    Args:
        signatures: {signature: {'count': int, 'paths': [path_d, ...]}}
        output_path: 输出HTML文件路径
        title: 页面标题
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5; }}
        h1 {{ color: #333; }}
        .controls {{ margin: 20px 0; padding: 15px; background: white; border-radius: 8px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 15px; }}
        .card {{
            border: 1px solid #ddd;
            padding: 15px;
            border-radius: 8px;
            background: white;
            text-align: center;
        }}
        .card.known {{ background: #e8f5e9; border-color: #4caf50; }}
        .card.unknown {{ background: #fff3e0; border-color: #ff9800; }}
        .glyph {{
            width: 60px;
            height: 60px;
            margin: 10px auto;
            display: block;
            border: 1px solid #eee;
            background: white;
        }}
        .sig {{ font-family: monospace; font-size: 11px; color: #666; word-break: break-all; }}
        .count {{ color: #1976d2; font-weight: bold; margin: 5px 0; }}
        .current-char {{ font-size: 20px; color: #388e3c; margin: 5px 0; }}
        input.char-input {{
            width: 50px;
            font-size: 16px;
            text-align: center;
            padding: 5px;
            border: 2px solid #ddd;
            border-radius: 4px;
        }}
        input.char-input:focus {{ border-color: #1976d2; outline: none; }}
        #export {{
            padding: 12px 24px;
            font-size: 16px;
            background: #1976d2;
            color: white;
            border: none;
            cursor: pointer;
            border-radius: 4px;
            margin-right: 10px;
        }}
        #export:hover {{ background: #1565c0; }}
        #stats {{ color: #666; margin-left: 20px; }}
        .filter-section {{ margin-bottom: 15px; }}
        .filter-section label {{ margin-right: 10px; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <div class="controls">
        <div class="filter-section">
            <label><input type="checkbox" id="showUnknown" checked> 显示未知签名</label>
            <label><input type="checkbox" id="showKnown" checked> 显示已知签名</label>
        </div>
        <button id="export" onclick="exportData()">导出签名映射 (JSON)</button>
        <span id="stats">总计 {len(signatures)} 个签名</span>
    </div>
    <div class="grid" id="grid">
"""

    known_sigs = load_signatures()
    sorted_sigs = sorted(signatures.items(), key=lambda x: -x[1]["count"])

    for sig, data in sorted_sigs:
        if data["count"] < 1:
            continue

        known_char = known_sigs.get(sig, "")
        card_class = "known" if known_char else "unknown"

        path_d = data["paths"][0] if data["paths"] else ""
        svg_content = (
            f'''<svg class="glyph" xmlns="http://www.w3.org/2000/svg" viewBox="-5 -15 25 25">
            <path d="{path_d}" fill="black" stroke="none" transform="scale(0.8,-0.8)"/>
        </svg>'''
            if path_d
            else '<div class="glyph"></div>'
        )

        display_char = known_char.replace("\\", "\\\\") if known_char else ""

        html += f'''
        <div class="card {card_class}" data-sig="{sig}" data-known="{1 if known_char else 0}">
            {svg_content}
            <div class="sig">{sig}</div>
            <div class="count">出现 {data["count"]} 次</div>
            <div class="current-char">{known_char or "?"}</div>
            <input type="text" class="char-input" value="{display_char}" placeholder="LaTeX">
        </div>
'''

    html += (
        """
    </div>
    <script>
        const knownSigs = """
        + json.dumps(known_sigs)
        + """;

        function exportData() {
            const cards = document.querySelectorAll('.card');
            const mapping = {};
            let newCount = 0;

            cards.forEach(card => {
                const sig = card.dataset.sig;
                const char = card.querySelector('.char-input').value.trim();
                if (char) {
                    mapping[sig] = char;
                    if (!knownSigs[sig]) newCount++;
                }
            });

            const json = JSON.stringify(mapping, null, 2);
            console.log('导出签名映射:', json);

            const blob = new Blob([json], {type: 'application/json'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'glyph_signatures.json';
            a.click();

            alert('已导出 ' + Object.keys(mapping).length + ' 个签名映射\\n其中新增 ' + newCount + ' 个');
        }

        function filterCards() {
            const showUnknown = document.getElementById('showUnknown').checked;
            const showKnown = document.getElementById('showKnown').checked;

            document.querySelectorAll('.card').forEach(card => {
                const isKnown = card.dataset.known === '1';
                if ((isKnown && showKnown) || (!isKnown && showUnknown)) {
                    card.style.display = '';
                } else {
                    card.style.display = 'none';
                }
            });
        }

        document.getElementById('showUnknown').addEventListener('change', filterCards);
        document.getElementById('showKnown').addEventListener('change', filterCards);

        // 输入框更新时更新显示
        document.querySelectorAll('.char-input').forEach(input => {
            input.addEventListener('input', function() {
                const card = this.closest('.card');
                const charDisplay = card.querySelector('.current-char');
                charDisplay.textContent = this.value || '?';

                // 更新卡片样式
                if (this.value.trim()) {
                    card.classList.remove('unknown');
                    card.classList.add('known');
                } else {
                    card.classList.remove('known');
                    card.classList.add('unknown');
                }
            });
        });
    </script>
</body>
</html>
"""
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"已生成签名分析页面: {output_path}")
    return output_path


# ============================================================================
# 测试函数
# ============================================================================


async def test():
    """运行内置测试"""
    print("=" * 60)
    print("SVG公式转LaTeX工具（增强版）- 测试")
    print("=" * 60)

    load_signatures()
    print(f"\n当前已加载 {len(GLYPH_SIGNATURES)} 个签名映射")

    # 测试1: 简单公式
    url1 = "https://staticzujuan.xkw.com/quesimg/Upload/formula/dad2a36927223bd70f426ba06aea4b45.svg"
    print(f"\n测试1 (简单公式): {url1.split('/')[-1]}")
    latex1, unknown1 = await svg_url_to_latex(url1)
    print(f"  LaTeX: {latex1}")
    if unknown1:
        print(f"  未知签名: {unknown1}")

    # 测试2: 复杂公式
    url2 = "https://staticzujuan.xkw.com/quesimg/Upload/formula/7c3a9b723303acf1669d4d88a7172b99.svg"
    print(f"\n测试2 (复杂公式): {url2.split('/')[-1]}")
    latex2, unknown2 = await svg_url_to_latex(url2)
    print(f"  LaTeX: {latex2}")
    if unknown2:
        print(f"  未知签名: {unknown2}")

    # 测试3: 高级转换
    print(f"\n测试3 (高级转换): {url2.split('/')[-1]}")
    latex3, unknown3 = await svg_url_to_latex(url2, use_advanced=True)
    print(f"  LaTeX: {latex3}")
    if unknown3:
        print(f"  未知签名: {unknown3}")

    print("\n" + "=" * 60)
    print(f"测试完成，当前已知签名数: {len(GLYPH_SIGNATURES)}")
    print("=" * 60)


# ============================================================================
# 命令行入口
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="SVG数学公式转LaTeX工具（字形签名精确匹配，非OCR）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s -u https://example.com/formula.svg
  %(prog)s -f formula.svg
  %(prog)s -H page.html -o output.html
  %(prog)s --collect -q 29811335 29811336 -o sigs.html
  %(prog)s --test
        """,
    )

    parser.add_argument("-u", "--url", action="append", help="SVG公式URL（可多次指定）")
    parser.add_argument("-f", "--file", action="append", help="本地SVG文件路径（可多次指定）")
    parser.add_argument("-H", "--html", help="包含公式图片的HTML文件（自动替换为LaTeX）")
    parser.add_argument("-o", "--output", help="输出文件路径")
    parser.add_argument("-c", "--concurrency", type=int, default=5, help="并发数（默认5）")
    parser.add_argument("--advanced", action="store_true", help="使用高级转换（支持分数等）")
    parser.add_argument("--test", action="store_true", help="运行内置测试")
    parser.add_argument("--collect", action="store_true", help="收集签名模式")
    parser.add_argument("-q", "--questions", nargs="+", help="题目ID列表（用于收集签名）")
    parser.add_argument("--add-sig", nargs=2, metavar=("SIG", "CHAR"), help="添加签名映射")
    parser.add_argument("--list-sigs", action="store_true", help="列出所有已知签名")

    args = parser.parse_args()

    # 添加签名
    if args.add_sig:
        sig, char = args.add_sig
        add_signature(sig, char)
        print(f"已添加签名: {sig} -> {char}")
        return

    # 列出签名
    if args.list_sigs:
        load_signatures()
        print(f"已知签名数: {len(GLYPH_SIGNATURES)}")
        for sig, char in sorted(GLYPH_SIGNATURES.items()):
            print(f"  {sig}: {char}")
        return

    # 运行测试
    if args.test:
        asyncio.run(test())
        return

    # 收集签名模式
    if args.collect:
        import urllib.request

        question_ids = args.questions or [str(29811335 + i) for i in range(5)]
        svg_urls = []

        print(f"从 {len(question_ids)} 个题目收集公式...")
        for qid in question_ids:
            url = f"https://zujuan.xkw.com/11q{qid}.html"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
                formulas = list(set(re.findall(r'https://[^"]+/formula/([^"]+)\.png', html)))[:30]
                for f_id in formulas:
                    svg_urls.append(f"https://staticzujuan.xkw.com/quesimg/Upload/formula/{f_id}.svg")
                print(f"  题目 {qid}: 找到 {len(formulas)} 个公式")
            except Exception as e:
                print(f"  题目 {qid}: 获取失败 - {e}")

        print(f"\n收集签名中（共 {len(svg_urls)} 个SVG）...")
        signatures = collect_signatures_from_urls(svg_urls)
        print(f"收集到 {len(signatures)} 个不同签名")

        output_path = args.output or os.path.join(os.path.dirname(__file__), "signature_analyzer.html")
        generate_signature_analyzer_html(signatures, output_path)
        return

    # 处理HTML文件
    if args.html:
        html_text = Path(args.html).read_text(encoding="utf-8")
        rendered, unknown = asyncio.run(
            replace_formulas_with_latex(html_text, concurrency=args.concurrency, use_advanced=args.advanced)
        )

        if args.output:
            Path(args.output).write_text(rendered, encoding="utf-8")
            print(f"已保存到: {args.output}")
        else:
            print(rendered)

        if unknown:
            print("\n未识别签名:")
            for url, sigs in unknown.items():
                print(f"  {url}: {', '.join(sigs)}")
        return

    # 处理URL和文件
    urls = args.url or []
    files = args.file or []

    if not urls and not files:
        parser.error("请提供 --url、--file 或 --html 参数")

    combined_results: Dict[str, Tuple[Optional[str], List[str]]] = {}

    if urls:
        combined_results.update(
            asyncio.run(batch_svg_to_latex(urls, concurrency=args.concurrency, use_advanced=args.advanced))
        )

    for svg_path in files:
        latex, unknown = svg_file_to_latex(svg_path, use_advanced=args.advanced)
        combined_results[svg_path] = (latex, unknown)

    for src in list(dict.fromkeys(urls + files)):
        latex, unknown = combined_results.get(src, (None, []))
        if latex:
            print(f"{src} -> {latex}")
        else:
            print(f"{src} -> <未能识别>")
        if unknown:
            print(f"  未知签名: {', '.join(unknown)}")


if __name__ == "__main__":
    main()
