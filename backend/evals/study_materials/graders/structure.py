"""成稿结构与格式评分：F 维度。

复用生成链路自己的判定件（``lint_text`` / ``split_sections_by_kp``），
保证 benchmark 与线上质量标准同源；另加现行成稿达不到的严格项
（目录锚点可跳转、标题层级无跳级）作为难度来源。
"""

from __future__ import annotations

import re
from typing import List

from backend.core.text_lint import lint_text
from backend.evals.study_materials.case_schema import BenchmarkCase
from backend.evals.study_materials.graders.common import DIMENSION_MAX, CheckResult, DimensionResult, make_dimension
from backend.generation.study_materials.coverage import split_sections_by_kp

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TOC_LINE_RE = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")
_MD_LINK_ANCHOR_RE = re.compile(r"\[([^\]]+)\]\(#([^)]+)\)")


def _headings(markdown: str) -> List[tuple[int, str]]:
    out: List[tuple[int, str]] = []
    in_fence = False
    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_RE.match(line)
        if m:
            out.append((len(m.group(1)), m.group(2)))
    return out


def _toc_block(markdown: str) -> List[str]:
    """“知识点目录”标题下的 bullet 行。"""
    lines = markdown.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^#{2,4}\s*.*(知识点目录|目录)\s*$", line.strip()):
            start = i + 1
            break
    if start is None:
        return []
    bullets: List[str] = []
    for line in lines[start:]:
        if line.strip().startswith("#"):
            break
        if _TOC_LINE_RE.match(line):
            bullets.append(line.strip())
        elif bullets and line.strip():
            break
    return bullets


def _slug(text: str) -> str:
    """与常见 markdown 渲染器一致的小写连字符锚点。"""
    text = re.sub(r"[`*_~]", "", text.strip().lower())
    text = re.sub(r"[\s]+", "-", text)
    return re.sub(r"[^\w一-鿿\-]", "", text)


def grade_structure(case: BenchmarkCase, markdown: str) -> DimensionResult:
    """F 维度：结构与格式（满分 DIMENSION_MAX['F']）。"""
    dim = make_dimension("F")
    total_max = DIMENSION_MAX["F"]
    part = total_max / 4.0
    text = markdown or ""
    headings = _headings(text)
    if not text.strip():
        for check_id, desc in (
            ("F1_skeleton", "必备骨架（标题/meta/使用建议/目录/逐kp小节/收尾）"),
            ("F2_toc_hierarchy", "目录为可跳转锚点链接、标题层级无跳级"),
            ("F3_math", "数学排版无 lint 残留、关键公式齐备"),
            ("F4_length", "篇幅达标"),
        ):
            dim.checks.append(CheckResult(check_id, desc, 0.0, part, "成稿为空"))
        return dim

    # F1 必备骨架
    skeleton_items: List[tuple[str, float]] = []
    skeleton_items.append(("H1 标题", 1.0 if any(level == 1 for level, _ in headings) else 0.0))
    skeleton_items.append(("meta 引用行（学科/预设）", 1.0 if re.search(r"^>\s*\S+", text, re.M) else 0.0))
    skeleton_items.append(("使用方式说明", 1.0 if "使用方式" in text or "使用建议" in text else 0.0))
    skeleton_items.append(("知识点目录", 1.0 if re.search(r"^#{2,4}\s*.*目录", text, re.M) else 0.0))
    sections_by_kp = split_sections_by_kp(text, case.expected_knowledge_points) if case.expected_knowledge_points else {}
    kp_matched = sum(1 for body in sections_by_kp.values() if body.strip())
    kp_total = max(1, len(case.expected_knowledge_points))
    skeleton_items.append((f"知识点小节匹配 {kp_matched}/{kp_total}", kp_matched / kp_total))
    skeleton_items.append(("收尾（分隔线/生成时间）", 1.0 if re.search(r"^---\s*$", text, re.M) or "生成时间" in text else 0.0))
    f1 = part * sum(score for _, score in skeleton_items) / len(skeleton_items)
    missing = [name for name, score in skeleton_items if score < 1.0]
    dim.checks.append(CheckResult(
        "F1_skeleton", "必备骨架（标题/meta/使用建议/目录/逐kp小节/收尾）",
        f1, part, "缺失: " + "、".join(missing) if missing else "骨架完整",
    ))

    # F2 目录锚点 + 标题层级
    toc = _toc_block(text)
    heading_slugs = {_slug(title) for _, title in headings}
    anchor_ok = 0
    for line in toc:
        m = _MD_LINK_ANCHOR_RE.search(line)
        if m and _slug(m.group(1)) in heading_slugs | {_slug(m.group(2))}:
            anchor_ok += 1
    anchor_ratio = (anchor_ok / len(toc)) if toc else 0.0
    anchor_score = (part / 2) * min(1.0, anchor_ratio / 0.8)
    level_skips = 0
    prev = 0
    for level, _ in headings:
        if prev and level > prev + 1:
            level_skips += 1
        prev = level
    hierarchy_score = (part / 2) if level_skips == 0 else ((part / 4) if level_skips <= 2 else 0.0)
    dim.checks.append(CheckResult(
        "F2_toc_hierarchy", "目录为可跳转锚点链接、标题层级无跳级",
        anchor_score + hierarchy_score, part,
        f"目录锚点 {anchor_ok}/{len(toc) or 0} 可跳转（现行成稿为纯文本 bullet）；层级跳级 {level_skips} 处",
    ))

    # F3 数学与关键公式
    flags = lint_text(text) if text.strip() else ["empty"]
    lint_score = (part / 2) if not flags else ((part / 4) if len(flags) == 1 else 0.0)
    formulas = case.format_requirements.key_formulas
    if formulas:
        hits = [p for p in formulas if re.search(p, text, re.IGNORECASE)]
        formula_score = (part / 2) * (len(hits) / len(formulas))
        formula_detail = f"关键公式命中 {len(hits)}/{len(formulas)}"
    else:
        formula_score = part / 2
        formula_detail = "用例无关键公式要求"
    dim.checks.append(CheckResult(
        "F3_math", "数学排版无 lint 残留、关键公式齐备",
        lint_score + formula_score, part,
        f"lint 标记 {len(flags)} 个（{';'.join(flags[:3]) or '无'}）；{formula_detail}",
    ))

    # F4 篇幅与信息密度
    min_chars = case.format_requirements.min_chars
    n_chars = len(text.strip())
    if min_chars > 0:
        f4 = part * min(1.0, n_chars / min_chars)
        detail = f"{n_chars} 字符 / 要求 ≥{min_chars}"
    else:
        f4 = part if n_chars > 0 else 0.0
        detail = f"{n_chars} 字符（用例未设下限）"
    dim.checks.append(CheckResult("F4_length", "篇幅达标", f4, part, detail))
    return dim
