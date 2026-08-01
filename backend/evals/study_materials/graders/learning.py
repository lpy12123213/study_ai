"""学习闭环评分：L 维度。

Challenge v2 不把“篇幅长、标题多”当成适合自学。成稿必须给出可检验目标、
带步骤的例题、分层自测以及与题号一一对应的答案/评分点。用例请求通过统一
输出契约约定 ``[EXn]``、``[Qn]``、``[An]`` 标签，使评分保持确定性。
"""

from __future__ import annotations

import re
from typing import List, Pattern, Set

from backend.evals.study_materials.case_schema import BenchmarkCase
from backend.evals.study_materials.graders.common import DIMENSION_MAX, CheckResult, DimensionResult, make_dimension

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)、])\s+\S", re.M)
_EXAMPLE_RE = re.compile(
    r"\[EX(?P<tag>\d+)\]|^(?:#{1,6}\s*)?(?:例题|示例|案例演练)\s*(?P<label>[一二三四五六七八九十\d]*)",
    re.IGNORECASE | re.M,
)
_QUESTION_TAG_RE = re.compile(r"\[Q(\d+)\]", re.IGNORECASE)
_ANSWER_TAG_RE = re.compile(r"\[A(\d+)\]", re.IGNORECASE)
_QUESTION_LINE_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)、])\s+\S.{0,500}[?？]\s*$", re.M)
_WORKED_CUE_RE = re.compile(r"(?:解答|解析|步骤|推导|计算过程|思路)")
_RUBRIC_CUE_RE = re.compile(r"(?:评分点|得分点|关键步骤|采分点|评分标准)")


def _without_fenced_code(markdown: str) -> str:
    lines: List[str] = []
    in_fence = False
    for line in (markdown or "").splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        # 归档 meta 会回显 benchmark requirements；引用行不是学习内容，必须剥离，
        # 否则协议里的 [EX1]/[Q1]/[A1] 标签会被误当成实际产物。
        if not in_fence and not line.lstrip().startswith(">"):
            lines.append(line)
    return "\n".join(lines)


def _section(markdown: str, title_pattern: Pattern[str]) -> str:
    """返回第一个匹配标题的小节正文，直到下一个同级或更高级标题。"""
    lines = (markdown or "").splitlines()
    start = -1
    level = 0
    in_fence = False
    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match and title_pattern.search(match.group(2)):
            start = index + 1
            level = len(match.group(1))
            break
    if start < 0:
        return ""
    end = len(lines)
    in_fence = False
    for index in range(start, len(lines)):
        line = lines[index]
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match and len(match.group(1)) <= level:
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def _worked_example_count(text: str) -> int:
    matches = list(_EXAMPLE_RE.finditer(text))
    counted: Set[str] = set()
    for index, match in enumerate(matches):
        label = match.group("tag") or match.group("label") or f"at-{match.start()}"
        key = str(label).casefold()
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(text), match.end() + 1600)
        if _WORKED_CUE_RE.search(text[match.end():end]):
            counted.add(key)
    return len(counted)


def grade_learning(case: BenchmarkCase, markdown: str) -> DimensionResult:
    """L 维度：面向学习者的目标—示例—练习—反馈闭环。"""
    dim = make_dimension("L")
    total_max = DIMENSION_MAX["L"]
    text = _without_fenced_code(markdown or "")
    req = case.learning_requirements

    if not text.strip():
        for check_id, description, ratio in (
            ("L1_goals_prerequisites", "可检验学习目标与前置知识", 0.20),
            ("L2_worked_examples", "带完整步骤的例题", 0.25),
            ("L3_practice_levels", "分层自测题（基础/应用/迁移）", 0.25),
            ("L4_answers_rubric", "题号对应的答案与评分点", 0.30),
        ):
            dim.checks.append(CheckResult(check_id, description, 0.0, total_max * ratio, "成稿为空"))
        return dim

    # L1：目标必须可枚举，前置知识必须有独立小节和实际内容。
    objectives = _section(text, re.compile(r"(?:学习目标|学习成果|本章目标)"))
    objective_count = len(_LIST_ITEM_RE.findall(objectives))
    prerequisites = _section(text, re.compile(r"(?:前置知识|先修知识|学习前提)"))
    prerequisites_ok = len(re.sub(r"\s+", "", prerequisites)) >= 12
    l1_max = total_max * 0.20
    l1 = l1_max * (
        0.75 * min(1.0, objective_count / req.min_objectives) + 0.25 * float(prerequisites_ok)
    )
    dim.checks.append(CheckResult(
        "L1_goals_prerequisites",
        "可检验学习目标与前置知识",
        l1,
        l1_max,
        f"学习目标 {objective_count}/{req.min_objectives}；前置知识小节 {'有效' if prerequisites_ok else '缺失或过空'}",
        metrics={"objective_count": objective_count, "prerequisites_ok": prerequisites_ok},
    ))

    # L2：只计算带“步骤/解答/解析”等过程说明的例题，单独出现“例题”二字不算。
    worked_examples = _worked_example_count(text)
    l2_max = total_max * 0.25
    l2 = l2_max * min(1.0, worked_examples / req.min_worked_examples)
    dim.checks.append(CheckResult(
        "L2_worked_examples",
        "带完整步骤的例题",
        l2,
        l2_max,
        f"有效例题 {worked_examples}/{req.min_worked_examples}（需 [EXn]/例题编号 + 解答步骤）",
        metrics={"worked_examples": worked_examples},
    ))

    # L3：标签是首选的可评分协议；无标签但确有问句时仅能获得数量项，不能冒充分层覆盖。
    question_section = _section(text, re.compile(r"(?:自测题|练习题|巩固练习|章节练习|自我检测)"))
    question_ids = set(_QUESTION_TAG_RE.findall(question_section or text))
    fallback_questions = len(_QUESTION_LINE_RE.findall(question_section)) if question_section else 0
    question_count = max(len(question_ids), fallback_questions)
    level_hits = [level for level in req.required_levels if f"[{level}]" in (question_section or text)]
    l3_max = total_max * 0.25
    quantity_ratio = min(1.0, question_count / req.min_practice_questions)
    levels_ratio = len(level_hits) / len(req.required_levels)
    l3 = l3_max * (0.70 * quantity_ratio + 0.30 * levels_ratio)
    dim.checks.append(CheckResult(
        "L3_practice_levels",
        "分层自测题（基础/应用/迁移）",
        l3,
        l3_max,
        f"题目 {question_count}/{req.min_practice_questions}；层级 {len(level_hits)}/{len(req.required_levels)}: {level_hits or '无'}",
        metrics={"question_count": question_count, "level_hits": level_hits},
    ))

    # L4：Q/A 标签必须一一对应；只有答案标题或泛泛解析不能形成反馈闭环。
    answer_section = _section(text, re.compile(r"(?:答案与评分点|参考答案|答案解析|评分标准)"))
    answer_ids = set(_ANSWER_TAG_RE.findall(answer_section or text))
    paired_ids = question_ids & answer_ids
    rubric_ok = bool(_RUBRIC_CUE_RE.search(answer_section))
    l4_max = total_max * 0.30
    pair_ratio = min(1.0, len(paired_ids) / req.min_answered_questions)
    l4 = l4_max * (0.85 * pair_ratio + 0.15 * float(rubric_ok))
    missing_answers = sorted(question_ids - answer_ids, key=lambda value: int(value))
    detail = f"Q/A 对应 {len(paired_ids)}/{req.min_answered_questions}；评分点 {'有' if rubric_ok else '无'}"
    if missing_answers:
        detail += f"；缺答案 Q{', Q'.join(missing_answers[:6])}"
    dim.checks.append(CheckResult(
        "L4_answers_rubric",
        "题号对应的答案与评分点",
        l4,
        l4_max,
        detail,
        metrics={"paired_count": len(paired_ids), "rubric_ok": rubric_ok},
    ))
    return dim
