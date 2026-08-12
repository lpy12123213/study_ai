"""学习闭环评分：L 维度。

Challenge v2 不把“篇幅长、标题多”当成适合自学。成稿必须给出可检验目标、
带步骤的例题、分层自测以及与题号一一对应的答案/评分点。用例请求通过统一
输出契约约定 ``[EXn]``、``[Qn]``、``[An]`` 标签，使评分保持确定性。
"""

from __future__ import annotations

from backend.evals.study_materials.case_schema import BenchmarkCase
from backend.evals.study_materials.graders.common import DIMENSION_MAX, CheckResult, DimensionResult, make_dimension
from backend.generation.study_materials.learning_contract import (
    LearningContractRequirements,
    inspect_learning_contract,
)


def grade_learning(case: BenchmarkCase, markdown: str) -> DimensionResult:
    """L 维度：面向学习者的目标—示例—练习—反馈闭环。"""
    dim = make_dimension("L")
    total_max = DIMENSION_MAX["L"]
    req = case.learning_requirements
    inspection = inspect_learning_contract(
        markdown or "",
        LearningContractRequirements(
            min_objectives=req.min_objectives,
            min_worked_examples=req.min_worked_examples,
            min_practice_questions=req.min_practice_questions,
            min_answered_questions=req.min_answered_questions,
            required_levels=list(req.required_levels),
        ),
    )

    if not str(markdown or "").strip():
        for check_id, description, ratio in (
            ("L1_goals_prerequisites", "可检验学习目标与前置知识", 0.20),
            ("L2_worked_examples", "带完整步骤的例题", 0.25),
            ("L3_practice_levels", "分层自测题（基础/应用/迁移）", 0.25),
            ("L4_answers_rubric", "题号对应的答案与评分点", 0.30),
        ):
            dim.checks.append(CheckResult(check_id, description, 0.0, total_max * ratio, "成稿为空"))
        return dim

    # L1：目标必须可枚举，前置知识必须有独立小节和实际内容。
    objective_count = int(inspection["objective_count"])
    prerequisites_ok = bool(inspection["prerequisites_ok"])
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
    worked_examples = int(inspection["worked_examples"])
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
    question_count = int(inspection["question_count"])
    level_hits = list(inspection["level_hits"])
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
    paired_count = int(inspection["paired_count"])
    rubric_ok = bool(inspection["rubric_ok"])
    l4_max = total_max * 0.30
    pair_ratio = min(1.0, paired_count / req.min_answered_questions)
    l4 = l4_max * (0.85 * pair_ratio + 0.15 * float(rubric_ok))
    missing_answers = list(inspection["missing_answers"])
    detail = f"Q/A 对应 {paired_count}/{req.min_answered_questions}；评分点 {'有' if rubric_ok else '无'}"
    if missing_answers:
        detail += f"；缺答案 Q{', Q'.join(missing_answers[:6])}"
    dim.checks.append(CheckResult(
        "L4_answers_rubric",
        "题号对应的答案与评分点",
        l4,
        l4_max,
        detail,
        metrics={"paired_count": paired_count, "rubric_ok": rubric_ok},
    ))
    return dim
