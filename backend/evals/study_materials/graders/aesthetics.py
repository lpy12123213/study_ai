"""美观与可读性评分：A 维度。

A1 图表与表格（确定性计数）；A2 排版质量，默认确定性代理（层级丰富度、
段落长度、排版元素多样性、小节结构一致性），``--llm-judge`` 时由 LLM 按
rubric 打分替换。完整的渲染版式评审（HTML/PDF 视觉评分）留作后续扩展。
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional

from backend.evals.study_materials.case_schema import BenchmarkCase
from backend.evals.study_materials.graders.common import DIMENSION_MAX, CheckResult, DimensionResult, make_dimension

# (markdown, case_title) -> 0..1 的排版质量分
LlmAestheticsJudge = Callable[[str, str], float]

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)|<svg[\s>]|```(?:tikz|asy|graphviz|dot)\b")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-{3,}[\s:|-]*\|", re.M)
_CAPTION_RE = re.compile(r"图\s*\d|图注|示意图|流程图|对比图")


def _count_figures(text: str) -> int:
    return len(_IMAGE_RE.findall(text))


def _count_tables(text: str) -> int:
    return len(_TABLE_SEP_RE.findall(text))


def _max_paragraph_chars(text: str) -> int:
    worst = 0
    buf: List[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal worst
        block = "\n".join(buf).strip()
        if block and not block.startswith(("#", ">", "-", "*", "|", "$$")):
            worst = max(worst, len(block))
        buf.clear()

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            flush()
            continue
        if in_fence:
            continue
        if not line.strip():
            flush()
        else:
            buf.append(line)
    flush()
    return worst


def grade_aesthetics(
    case: BenchmarkCase,
    markdown: str,
    *,
    llm_judge: Optional[LlmAestheticsJudge] = None,
) -> DimensionResult:
    """A 维度：美观与可读性（满分 DIMENSION_MAX['A']）。"""
    dim = make_dimension("A")
    total_max = DIMENSION_MAX["A"]
    text = markdown or ""
    if not text.strip():
        dim.checks.append(CheckResult("A1_figures_tables", "示意图/表格数量达标", 0.0, total_max * 0.4, "成稿为空"))
        dim.checks.append(CheckResult(
            "A2_typesetting", "排版质量（确定性代理；--llm-judge 可换 LLM rubric）",
            0.0, total_max * 0.6, "成稿为空",
        ))
        return dim

    # A1 图表与表格
    half = total_max * 0.4
    figures = _count_figures(text)
    tables = _count_tables(text)
    captions = len(_CAPTION_RE.findall(text))
    fig_req = case.format_requirements.min_figures
    tab_req = case.format_requirements.min_tables
    fig_score = (half / 2) if fig_req == 0 else (half / 2) * min(1.0, figures / fig_req)
    tab_score = (half / 2) if tab_req == 0 else (half / 2) * min(1.0, tables / tab_req)
    dim.checks.append(CheckResult(
        "A1_figures_tables", "示意图/表格数量达标",
        fig_score + tab_score, half,
        f"图 {figures}（要求≥{fig_req}）、表格 {tables}（要求≥{tab_req}）、图注 {captions} 处",
    ))

    # A2 排版质量
    half2 = total_max * 0.6
    if llm_judge is not None:
        try:
            ratio = float(llm_judge(text, case.title))
            ratio = max(0.0, min(1.0, ratio))
            dim.checks.append(CheckResult(
                "A2_typesetting_llm", "排版质量（LLM rubric 评审）",
                half2 * ratio, half2, f"LLM 评分比例 {ratio:.2f}",
            ))
            return dim
        except Exception:  # noqa: BLE001 - judge 故障回退确定性代理
            pass

    sub = half2 / 4.0
    proxy_checks: List[tuple[str, bool, str]] = []
    levels = {len(m.group(1)) for m in re.finditer(r"^(#{1,6})\s", text, re.M)}
    proxy_checks.append(("标题层级丰富（≥3 级）", len(levels) >= 3, f"实际 {len(levels)} 级"))
    worst = _max_paragraph_chars(text)
    proxy_checks.append(("无超长段落（≤1500 字符）", worst <= 1500, f"最长段落 {worst} 字符"))
    elements = 0
    elements += 1 if re.search(r"\$\$[^\$]+\$\$", text, re.S) else 0
    elements += 1 if tables else 0
    elements += 1 if re.search(r"^>\s", text, re.M) else 0
    elements += 1 if figures else 0
    elements += 1 if re.search(r"^\s*[-*+]\s", text, re.M) else 0
    proxy_checks.append(("排版元素多样（公式/表格/引用/图/列表 ≥4 类）", elements >= 4, f"命中 {elements} 类"))
    h2 = len(re.findall(r"^##\s", text, re.M))
    h3 = len(re.findall(r"^###\s", text, re.M))
    proxy_checks.append(("二级小节多数有三级结构", h2 == 0 or h3 >= 0.5 * h2, f"## {h2} 个 / ### {h3} 个"))
    a2 = sum(sub for _, ok, _ in proxy_checks if ok)
    failed = [f"{name}（{note}）" for name, ok, note in proxy_checks if not ok]
    dim.checks.append(CheckResult(
        "A2_typesetting", "排版质量（确定性代理；--llm-judge 可换 LLM rubric）",
        a2, half2, "未达标: " + "；".join(failed) if failed else "全部达标",
    ))
    return dim
