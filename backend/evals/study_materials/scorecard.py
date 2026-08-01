"""成绩卡：汇总六个维度 → 百分制总分 + JSON/Markdown 报告。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.evals.study_materials.case_schema import BenchmarkCase
from backend.evals.study_materials.graders.aesthetics import grade_aesthetics
from backend.evals.study_materials.graders.citations import LinkChecker, grade_citations
from backend.evals.study_materials.graders.common import DimensionResult, validate_weights
from backend.evals.study_materials.graders.events import grade_research, grade_subagents
from backend.evals.study_materials.graders.knowledge import LlmFactJudge, grade_knowledge
from backend.evals.study_materials.graders.structure import grade_structure


@dataclass
class Scorecard:
    case_id: str
    title: str
    dimensions: List[DimensionResult] = field(default_factory=list)
    generated_at: str = ""
    notes: List[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(d.score for d in self.dimensions)

    @property
    def total_max(self) -> float:
        return sum(d.max_score for d in self.dimensions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "total": round(self.total, 2),
            "total_max": round(self.total_max, 2),
            "generated_at": self.generated_at,
            "notes": self.notes,
            "dimensions": [d.to_dict() for d in self.dimensions],
        }


def grade_case(
    case: BenchmarkCase,
    events: List[Dict[str, Any]],
    markdown: str,
    *,
    task_info: Optional[Dict[str, Any]] = None,
    llm_fact_judge: Optional[LlmFactJudge] = None,
    llm_aesthetics_judge: Optional[Callable[[str, str], float]] = None,
    link_checker: Optional[LinkChecker] = None,
    notes: Optional[List[str]] = None,
) -> Scorecard:
    """对一次生成结果完整评分。所有 grader 均为确定性纯函数，judge 可注入。"""
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
    card.dimensions.append(grade_research(case, events, task_info=task_info))
    card.dimensions.append(grade_knowledge(case, markdown, llm_judge=llm_fact_judge, citation_ratio=citation_ratio))
    card.dimensions.append(grade_subagents(case, events))
    card.dimensions.append(grade_structure(case, markdown))
    card.dimensions.append(grade_aesthetics(case, markdown, llm_judge=llm_aesthetics_judge))
    card.dimensions.append(citations)
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
    lines.append(f"- 总分：**{card.total:.1f} / {card.total_max:.0f}**")
    lines.append(f"- 评分时间：{card.generated_at}")
    for note in card.notes:
        lines.append(f"- 备注：{note}")
    lines.append("")
    lines.append("| 维度 | 得分 | 满分 | 主要失分点 |")
    lines.append("|---|---|---|---|")
    for d in card.dimensions:
        lost = [c.id for c in d.checks if c.score < c.max_score * 0.5]
        lines.append(f"| {d.dimension} {d.title} | {d.score:.1f} | {d.max_score:.0f} | {'、'.join(lost) or '—'} |")
    lines.append("")
    for d in card.dimensions:
        lines.append(f"## {d.dimension} {d.title}（{d.score:.1f}/{d.max_score:.0f}）")
        lines.append("")
        for c in d.checks:
            lines.append(f"- `{c.id}` {c.description}：**{c.score:.1f}**/{c.max_score:.0f} — {c.detail}")
        lines.append("")
    return "\n".join(lines)
