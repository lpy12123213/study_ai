"""Challenge v2 成绩卡：原始诊断分 + 必要质量门槛 → 最终成熟度分。"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.core.text_lint import lint_text
from backend.evals.study_materials.case_schema import BenchmarkCase
from backend.evals.study_materials.graders.aesthetics import grade_aesthetics
from backend.evals.study_materials.graders.citations import LinkChecker, grade_citations
from backend.evals.study_materials.graders.common import DimensionResult, validate_weights
from backend.evals.study_materials.graders.events import grade_research, grade_subagents
from backend.evals.study_materials.graders.knowledge import LlmFactJudge, grade_knowledge
from backend.evals.study_materials.graders.learning import grade_learning
from backend.evals.study_materials.graders.rubric import LlmRubricJudge, grade_rubric
from backend.evals.study_materials.graders.structure import grade_structure
from backend.generation.study_materials.coverage import split_sections_by_kp

SCORING_VERSION = "challenge_v2"


@dataclass
class QualityGateResult:
    id: str
    title: str
    passed: bool
    ceiling: float
    detail: str
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "passed": self.passed,
            "ceiling": round(self.ceiling, 2),
            "detail": self.detail,
            "metrics": self.metrics,
        }


@dataclass
class Scorecard:
    case_id: str
    title: str
    dimensions: List[DimensionResult] = field(default_factory=list)
    quality_gates: List[QualityGateResult] = field(default_factory=list)
    process_diagnostics: List[DimensionResult] = field(default_factory=list)
    generated_at: str = ""
    notes: List[str] = field(default_factory=list)
    scoring_version: str = SCORING_VERSION
    # LLM rubric 写作诊断（W 维度）：独立字段仅报告展示，不进总分/四门槛/成熟度。
    writing_rubric: Optional[Dict[str, Any]] = None

    @property
    def raw_total(self) -> float:
        """六个最终质量维度的加总；用于定位改进，不代表已经可交付。"""
        return sum(d.score for d in self.dimensions)

    @property
    def applied_ceiling(self) -> float:
        failed = [gate.ceiling for gate in self.quality_gates if not gate.passed]
        return min(failed) if failed else 100.0

    @property
    def total(self) -> float:
        """最终成熟度分：原始诊断分受最严格的未通过质量门槛封顶。"""
        return min(self.raw_total, self.applied_ceiling)

    @property
    def total_max(self) -> float:
        return sum(d.max_score for d in self.dimensions)

    @property
    def readiness_level(self) -> str:
        score = self.total
        if score < 10:
            return "不可交付"
        if score < 20:
            return "未达自学基线"
        if score < 40:
            return "结构化草稿"
        if score < 60:
            return "可试用"
        if score < 80:
            return "合格"
        return "优秀"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scoring_version": self.scoring_version,
            "case_id": self.case_id,
            "title": self.title,
            "total": round(self.total, 2),
            "raw_total": round(self.raw_total, 2),
            "total_max": round(self.total_max, 2),
            "applied_ceiling": round(self.applied_ceiling, 2),
            "readiness_level": self.readiness_level,
            "generated_at": self.generated_at,
            "notes": self.notes,
            "quality_gates": [gate.to_dict() for gate in self.quality_gates],
            "dimensions": [dimension.to_dict() for dimension in self.dimensions],
            "process_diagnostics": [dimension.to_dict() for dimension in self.process_diagnostics],
            "writing_rubric": self.writing_rubric,
        }


def _check_by_id(dimensions: List[DimensionResult], dimension: str, check_id: str):  # noqa: ANN202
    for item in dimensions:
        if item.dimension != dimension:
            continue
        for check in item.checks:
            if check.id == check_id:
                return check
    return None


def _ratio(check: Any) -> float:
    if check is None or float(check.max_score or 0.0) <= 0:
        return 0.0
    return max(0.0, min(1.0, float(check.score) / float(check.max_score)))


def _delivery_lint_flags(markdown: str) -> List[str]:
    # 正常归档以“生成时间：YYYY...”收尾；先移除该机器元数据，避免把末尾数字误判为截断。
    cleaned = re.sub(r"\n---\s*\n生成时间[:：][^\n]+\s*$", "\n正文完。", markdown or "")
    return lint_text(cleaned)


def _build_quality_gates(
    case: BenchmarkCase,
    events: List[Dict[str, Any]],
    markdown: str,
    dimensions: List[DimensionResult],
    task_info: Optional[Dict[str, Any]],
) -> List[QualityGateResult]:
    """把不可替代的用户需求建模为门槛，而不是允许无关加分相互抵消。"""
    gates: List[QualityGateResult] = []
    info = task_info if isinstance(task_info, dict) else {}
    event_types = [str(frame.get("type") or frame.get("event") or "") for frame in events if isinstance(frame, dict)]
    terminal_ok = "done" in event_types or str(info.get("status") or "").lower() in {
        "completed",
        "done",
        "success",
        "succeeded",
    }
    terminal_error = "error" in event_types or bool(str(info.get("error") or "").strip())
    min_chars = max(1, case.format_requirements.min_chars)
    char_count = len((markdown or "").strip())
    length_ratio = min(1.0, char_count / min_chars)
    sections = split_sections_by_kp(markdown or "", case.expected_knowledge_points)
    matched_sections = sum(1 for body in sections.values() if body.strip())
    kp_ratio = matched_sections / max(1, len(case.expected_knowledge_points))
    lint_flags = _delivery_lint_flags(markdown)
    delivery_ok = (
        terminal_ok
        and not terminal_error
        and length_ratio >= 1.0
        and kp_ratio >= 0.8
        and not lint_flags
    )
    gates.append(QualityGateResult(
        "G0_delivery",
        "完整交付",
        delivery_ok,
        9.0,
        (
            f"终态={'成功' if terminal_ok and not terminal_error else '失败/未知'}；"
            f"篇幅={char_count}/{min_chars}；知识点小节={matched_sections}/{len(case.expected_knowledge_points)}；"
            f"lint={lint_flags or '无'}"
        ),
        metrics={
            "terminal_ok": terminal_ok and not terminal_error,
            "length_ratio": round(length_ratio, 4),
            "kp_coverage_ratio": round(kp_ratio, 4),
            "lint_flags": lint_flags,
        },
    ))

    k1 = _check_by_id(dimensions, "K", "K1_facts")
    k2 = _check_by_id(dimensions, "K", "K2_traps")
    k3 = _check_by_id(dimensions, "K", "K3_contrasts")
    fact_ratio = float((k1.metrics if k1 else {}).get("matched_ratio") or 0.0)
    correctness_ok = fact_ratio >= 0.8 and _ratio(k2) >= 0.8 and _ratio(k3) >= 0.8
    gates.append(QualityGateResult(
        "G1_correctness",
        "核心正确性",
        correctness_ok,
        19.0,
        f"事实命中={fact_ratio:.0%}；误区驳正={_ratio(k2):.0%}；概念辨析={_ratio(k3):.0%}",
        metrics={
            "fact_ratio": round(fact_ratio, 4),
            "trap_ratio": round(_ratio(k2), 4),
            "contrast_ratio": round(_ratio(k3), 4),
        },
    ))

    c1 = _check_by_id(dimensions, "C", "C1_references_section")
    c2 = _check_by_id(dimensions, "C", "C2_inline_markers")
    c3 = _check_by_id(dimensions, "C", "C3_authority_domains")
    evidence_ok = _ratio(c1) >= 0.75 and _ratio(c2) >= 0.75 and _ratio(c3) >= 0.5
    gates.append(QualityGateResult(
        "G2_evidence",
        "证据闭环",
        evidence_ok,
        19.0,
        f"参考文献={_ratio(c1):.0%}；内联对应={_ratio(c2):.0%}；权威来源={_ratio(c3):.0%}",
        metrics={
            "references_ratio": round(_ratio(c1), 4),
            "inline_ratio": round(_ratio(c2), 4),
            "authority_ratio": round(_ratio(c3), 4),
        },
    ))

    learning = next((item for item in dimensions if item.dimension == "L"), None)
    l4 = _check_by_id(dimensions, "L", "L4_answers_rubric")
    learning_ratio = float(learning.score / learning.max_score) if learning and learning.max_score else 0.0
    learning_ok = learning_ratio >= 0.7 and _ratio(l4) >= 0.7
    gates.append(QualityGateResult(
        "G3_learning_loop",
        "学习反馈闭环",
        learning_ok,
        39.0,
        f"学习维度={learning_ratio:.0%}；Q/A与评分点={_ratio(l4):.0%}",
        metrics={"learning_ratio": round(learning_ratio, 4), "answer_ratio": round(_ratio(l4), 4)},
    ))
    return gates


def grade_case(
    case: BenchmarkCase,
    events: List[Dict[str, Any]],
    markdown: str,
    *,
    task_info: Optional[Dict[str, Any]] = None,
    llm_fact_judge: Optional[LlmFactJudge] = None,
    llm_aesthetics_judge: Optional[Callable[[str, str], float]] = None,
    llm_rubric_judge: Optional[LlmRubricJudge] = None,
    link_checker: Optional[LinkChecker] = None,
    notes: Optional[List[str]] = None,
) -> Scorecard:
    """对一次生成结果完整评分；LLM 与联网检查均是可选诊断增强。"""
    validate_weights()
    card = Scorecard(
        case_id=case.id,
        title=case.title,
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        notes=list(notes or []),
    )
    citations = grade_citations(case, markdown, link_checker=link_checker)
    citation_ratio = 0.0
    for check in citations.checks:
        if check.id == "C2_inline_markers" and check.max_score > 0:
            citation_ratio = check.score / check.max_score
    card.dimensions.extend([
        grade_research(case, events, task_info=task_info),
        grade_knowledge(case, markdown, llm_judge=llm_fact_judge, citation_ratio=citation_ratio),
        grade_learning(case, markdown),
        grade_structure(case, markdown),
        grade_aesthetics(case, markdown, llm_judge=llm_aesthetics_judge),
        citations,
    ])
    card.process_diagnostics.append(grade_subagents(case, events))
    # W 维度：仅 judge 启用时调用的独立 LLM 诊断，不进总分与四门槛（同 aesthetics 注入模式）。
    if llm_rubric_judge is not None:
        card.writing_rubric = grade_rubric(markdown, judge_func=llm_rubric_judge)["W"]
    card.quality_gates = _build_quality_gates(case, events, markdown, card.dimensions, task_info)
    return card


def write_outputs(card: Scorecard, out_dir: Path) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    score_path = out / "score.json"
    score_path.write_text(json.dumps(card.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = out / "report.md"
    report_path.write_text(render_report(card), encoding="utf-8")
    return {"score": score_path, "report": report_path}


def render_report(card: Scorecard) -> str:
    lines: List[str] = []
    lines.append(f"# Benchmark 报告：{card.title}（{card.case_id}）")
    lines.append("")
    lines.append(f"- 最终成熟度分：**{card.total:.1f} / {card.total_max:.0f}**（{card.readiness_level}）")
    lines.append(f"- 原始诊断分：**{card.raw_total:.1f} / {card.total_max:.0f}**")
    lines.append(f"- 当前封顶：**{card.applied_ceiling:.1f}**（未通过的必要门槛不能由无关加分抵消）")
    lines.append(f"- 评分版本：`{card.scoring_version}`；评分时间：{card.generated_at}")
    for note in card.notes:
        lines.append(f"- 备注：{note}")
    lines.append("")
    lines.append("## 必要质量门槛")
    lines.append("")
    lines.append("| 门槛 | 状态 | 未通过时封顶 | 判定证据 |")
    lines.append("|---|---|---:|---|")
    for gate in card.quality_gates:
        lines.append(
            f"| {gate.id} {gate.title} | {'通过' if gate.passed else '未通过'} | "
            f"{gate.ceiling:.0f} | {gate.detail} |"
        )
    lines.append("")
    lines.append("## 百分制诊断维度")
    lines.append("")
    lines.append("| 维度 | 得分 | 满分 | 主要失分点 |")
    lines.append("|---|---:|---:|---|")
    for dimension in card.dimensions:
        lost = [check.id for check in dimension.checks if check.score < check.max_score * 0.5]
        lines.append(
            f"| {dimension.dimension} {dimension.title} | {dimension.score:.1f} | "
            f"{dimension.max_score:.0f} | {'、'.join(lost) or '—'} |"
        )
    lines.append("")
    for dimension in card.dimensions:
        lines.append(f"### {dimension.dimension} {dimension.title}（{dimension.score:.1f}/{dimension.max_score:.0f}）")
        lines.append("")
        for check in dimension.checks:
            lines.append(
                f"- `{check.id}` {check.description}：**{check.score:.1f}**/{check.max_score:.0f} — {check.detail}"
            )
        lines.append("")
    lines.append("## 过程诊断（不计入总分）")
    lines.append("")
    for dimension in card.process_diagnostics:
        lines.append(f"### {dimension.dimension} {dimension.title}（{dimension.score:.1f}/{dimension.max_score:.0f}）")
        lines.append("")
        for check in dimension.checks:
            lines.append(f"- `{check.id}` {check.description}：{check.score:.1f}/{check.max_score:.0f} — {check.detail}")
        lines.append("")
    lines.append("## 写作 rubric 诊断（LLM，不计入总分）")
    lines.append("")
    if card.writing_rubric:
        rubric = card.writing_rubric
        rationale = rubric.get("rationale") or {}
        labels = (
            ("coherence", "连贯性"),
            ("style", "文风"),
            ("misconception_authenticity", "易错点真实性"),
        )
        for key, label in labels:
            score = rubric.get(key)
            reason = str(rationale.get(key) or "")
            suffix = f" — {reason}" if reason else ""
            shown = f"{score}/5" if score is not None else "—"
            lines.append(f"- {label}（{key}）：{shown}{suffix}")
        if rubric.get("error"):
            lines.append(f"- 诊断未生效：{rubric['error']}")
    else:
        lines.append("- 未启用 LLM judge（--llm-judge 时生成该诊断）。")
    lines.append("")
    return "\n".join(lines)
