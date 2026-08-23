"""AI 出题质量评分：确定性维度 + 必要质量门槛 → 最终成熟度分。

维度（合计 100）：
- D1 交付（25）：出足数量、题干/答案/解析三段完整、题干之间不近重复；
- D2 正确性（35）：逐题命中题干/答案/解析锚点且不触发禁用模式；
- D3 教学性（25）：解析有步骤线索与足量篇幅、知识点术语进入题目；
- D4 契约（15）：题面结构与题型匹配、答案形态与题型匹配。

门槛（未通过则封顶）：GQ_delivery 交付下限；GQ_correctness 正确性下限。
生成链路自评（review verdict/score）只作过程诊断，不计入分数。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.evals.question_generation.case_schema import QuestionCase
from backend.generation.question_library.evolution_penalties import evaluate_evolution_penalties

DIMENSION_MAX: Dict[str, float] = {
    "D1_delivery": 25.0,
    "D2_correctness": 35.0,
    "D3_pedagogy": 25.0,
    "D4_contract": 15.0,
}

_DELIVERY_GATE_CEILING = 9.0
_CORRECTNESS_GATE_CEILING = 19.0
_DELIVERY_COUNT_RATIO = 0.8
_CORRECTNESS_RATIO = 0.8

# 近重复判定：归一化文本的字符二元组 Jaccard ≥ 阈值视为同一题换皮。
_DUPLICATE_JACCARD = 0.82

_STEP_CUE_RE = re.compile(r"由|因为|所以|代入|解得|得|则|即|故|首先|其次|因此|根据|于是|进而|可得|将|取|先|再")
_TYPE_CUES: Dict[str, re.Pattern[str]] = {
    "选择题": re.compile(r"A[.、．)）]|B[.、．)）]|①|选项"),
    "填空题": re.compile(r"_{2,}|＿{2,}|（\s*）|\(\s*\)|填空|空中"),
    "解答题": re.compile(r"求|证明|计算|讨论|解[：:]|设"),
}
_ANSWER_FORM_RES: Dict[str, re.Pattern[str]] = {
    "选择题": re.compile(r"^\s*[A-D](?:[.、．)）]|\s|$)|选项"),
    "填空题": re.compile(r"\S"),
    "解答题": re.compile(r"\S"),
}


@dataclass
class CheckResult:
    id: str
    description: str
    score: float
    max_score: float
    detail: str
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
    score: float
    max_score: float
    checks: List[CheckResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "title": self.title,
            "score": round(self.score, 2),
            "max_score": round(self.max_score, 2),
            "checks": [c.to_dict() for c in self.checks],
        }


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
class PenaltyResult:
    id: str
    title: str
    points: float
    max_points: float
    detail: str
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "points": round(self.points, 2),
            "max_points": round(self.max_points, 2),
            "detail": self.detail,
            "metrics": self.metrics,
        }


@dataclass
class QuestionScorecard:
    case_id: str
    title: str
    dimensions: List[DimensionResult] = field(default_factory=list)
    quality_gates: List[QualityGateResult] = field(default_factory=list)
    process_diagnostics: List[CheckResult] = field(default_factory=list)
    evolution_penalties: List[PenaltyResult] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    scoring_version: str = "question_gen_v2"

    @property
    def pre_penalty_total(self) -> float:
        return sum(d.score for d in self.dimensions)

    @property
    def penalty_total(self) -> float:
        return sum(p.points for p in self.evolution_penalties)

    @property
    def raw_total(self) -> float:
        return max(0.0, self.pre_penalty_total - self.penalty_total)

    @property
    def applied_ceiling(self) -> float:
        failed = [g.ceiling for g in self.quality_gates if not g.passed]
        return min(failed) if failed else 100.0

    @property
    def total(self) -> float:
        return min(self.raw_total, self.applied_ceiling)

    @property
    def total_max(self) -> float:
        return sum(d.max_score for d in self.dimensions)

    @property
    def readiness_level(self) -> str:
        score = self.total
        if score < 10:
            return "不可用"
        if score < 20:
            return "未达出题基线"
        if score < 40:
            return "需人工重写"
        if score < 60:
            return "可人工修订后入库"
        if score < 80:
            return "可用"
        return "优秀"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scoring_version": self.scoring_version,
            "case_id": self.case_id,
            "title": self.title,
            "total": round(self.total, 2),
            "raw_total": round(self.raw_total, 2),
            "pre_penalty_total": round(self.pre_penalty_total, 2),
            "penalty_total": round(self.penalty_total, 2),
            "total_max": round(self.total_max, 2),
            "applied_ceiling": round(self.applied_ceiling, 2),
            "readiness_level": self.readiness_level,
            "notes": self.notes,
            "quality_gates": [g.to_dict() for g in self.quality_gates],
            "dimensions": [d.to_dict() for d in self.dimensions],
            "process_diagnostics": [c.to_dict() for c in self.process_diagnostics],
            "evolution_penalties": [p.to_dict() for p in self.evolution_penalties],
        }


def _draft_text(draft: Any, key: str) -> str:
    if isinstance(draft, dict):
        return str(draft.get(key) or "")
    return str(getattr(draft, key, "") or "")


def _normalize_for_dup(text: str) -> str:
    return re.sub(r"[\s\d\W_]+", "", (text or "").lower(), flags=re.UNICODE)


def _bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(max(0, len(text) - 1))}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_duplicate_stems(drafts: List[Dict[str, Any]]) -> List[int]:
    """返回与更早题干近重复的草稿下标（0-based）。"""
    normals = [_normalize_for_dup(_draft_text(d, "stem")) for d in drafts]
    grams = [_bigrams(n) if len(n) >= 2 else set() for n in normals]
    duplicates: List[int] = []
    for i in range(len(drafts)):
        for j in range(i):
            if grams[i] and grams[j] and _jaccard(grams[i], grams[j]) >= _DUPLICATE_JACCARD:
                duplicates.append(i)
                break
    return duplicates


def _match_all(patterns: List[str], text: str) -> Tuple[bool, List[str]]:
    missed = [p for p in patterns if not re.search(p, text, re.IGNORECASE)]
    return (not missed), missed


def _kp_tokens(kp: str) -> List[str]:
    return [t for t in re.split(r"[与和、，,/·\s]+", kp) if len(t) >= 2]


def _kp_token_hit(kp: str, text: str) -> bool:
    """知识点命中：整串子串，或单份草稿内出现过半数语义片段。

    shipped 用例的知识点是长短语（如「椭圆的标准方程与几何性质」），
    正确题目很少逐字复述整串；按片段过半匹配保持教学性检查又不至于恒零。
    """

    if kp in text:
        return True
    tokens = _kp_tokens(kp)
    if not tokens:
        return False
    need = (len(tokens) + 1) // 2
    hits = sum(1 for t in tokens if t in text)
    return hits >= need


def grade_case(
    case: QuestionCase,
    drafts: List[Dict[str, Any]],
    *,
    notes: Optional[List[str]] = None,
) -> QuestionScorecard:
    """对一次出题预览的草稿列表完整评分（全部确定性判定，不调 LLM）。"""
    card = QuestionScorecard(case_id=case.id, title=case.title, notes=list(notes or []))
    drafts = [d for d in (drafts or []) if isinstance(d, dict)]

    delivered = len(drafts)
    requested = max(1, case.count)
    count_ratio = min(1.0, delivered / requested)

    sections_ok_flags: List[bool] = []
    anchor_ok_flags: List[bool] = []
    stem_anchor_misses: List[str] = []
    answer_anchor_misses: List[str] = []
    forbidden_hits: List[int] = []
    step_ok_flags: List[bool] = []
    analysis_len_flags: List[bool] = []
    type_cue_flags: List[bool] = []
    answer_form_flags: List[bool] = []

    for index, draft in enumerate(drafts):
        stem = _draft_text(draft, "stem")
        answer = _draft_text(draft, "answer")
        analysis = _draft_text(draft, "analysis")
        combined = f"{stem}\n{answer}\n{analysis}"

        sections_ok = len(stem.strip()) >= case.min_stem_chars and bool(answer.strip()) and bool(analysis.strip())
        sections_ok_flags.append(sections_ok)

        stem_ok, stem_missed = _match_all(case.stem_anchors, stem)
        answer_ok, answer_missed = _match_all(case.answer_anchors, f"{answer}\n{analysis}")
        analysis_ok, _ = _match_all(case.analysis_anchors, analysis)
        anchor_ok = stem_ok and answer_ok and analysis_ok
        anchor_ok_flags.append(anchor_ok)
        if stem_missed:
            stem_anchor_misses.append(f"#{index + 1}: {'、'.join(stem_missed)}")
        if answer_missed:
            answer_anchor_misses.append(f"#{index + 1}: {'、'.join(answer_missed)}")
        if anchor_ok and not sections_ok:
            anchor_ok_flags[-1] = False

        if any(re.search(p, combined, re.IGNORECASE) for p in case.forbidden_patterns):
            forbidden_hits.append(index)

        cues = set(_STEP_CUE_RE.findall(analysis))
        step_ok_flags.append(len(cues) >= 2)
        analysis_len_flags.append(len(analysis.strip()) >= case.min_analysis_chars)

        type_cue = _TYPE_CUES.get(case.question_type)
        type_cue_flags.append(bool(type_cue and type_cue.search(stem)))
        answer_form = _ANSWER_FORM_RES.get(case.question_type)
        answer_form_flags.append(bool(answer_form and answer_form.search(answer.strip())))

    sections_ratio = sum(sections_ok_flags) / max(1, delivered)
    anchor_ratio = sum(anchor_ok_flags) / max(1, delivered)
    duplicates = find_duplicate_stems(drafts)
    distinct_ratio = (delivered - len(duplicates)) / max(1, delivered)

    dim1 = DimensionResult("D1", "交付完整度", 0.0, DIMENSION_MAX["D1_delivery"])
    dim1.checks.append(CheckResult(
        "D1a_count", f"交付数量 {delivered}/{requested}", DIMENSION_MAX["D1_delivery"] * 0.4 * count_ratio,
        DIMENSION_MAX["D1_delivery"] * 0.4, f"数量比例 {count_ratio:.0%}",
        {"delivered": delivered, "requested": requested},
    ))
    dim1.checks.append(CheckResult(
        "D1b_sections", f"题干/答案/解析完整 {sum(sections_ok_flags)}/{delivered}",
        DIMENSION_MAX["D1_delivery"] * 0.3 * sections_ratio, DIMENSION_MAX["D1_delivery"] * 0.3,
        f"完整比例 {sections_ratio:.0%}", {"sections_ratio": round(sections_ratio, 4)},
    ))
    dim1.checks.append(CheckResult(
        "D1c_distinct", f"题干不近重复 {delivered - len(duplicates)}/{delivered}",
        DIMENSION_MAX["D1_delivery"] * 0.3 * distinct_ratio, DIMENSION_MAX["D1_delivery"] * 0.3,
        f"近重复下标 {duplicates or '无'}", {"duplicate_indexes": duplicates},
    ))
    dim1.score = sum(c.score for c in dim1.checks)

    dim2 = DimensionResult("D2", "答案正确性", 0.0, DIMENSION_MAX["D2_correctness"])
    forbidden_count = len(forbidden_hits)
    dim2.checks.append(CheckResult(
        "D2a_anchors", f"锚点全部命中 {sum(anchor_ok_flags)}/{delivered}",
        DIMENSION_MAX["D2_correctness"] * anchor_ratio, DIMENSION_MAX["D2_correctness"],
        (
            f"题干锚点未命中: {'；'.join(stem_anchor_misses) or '无'}；"
            f"答案锚点未命中: {'；'.join(answer_anchor_misses) or '无'}"
        ),
        {"anchor_ratio": round(anchor_ratio, 4)},
    ))
    if forbidden_count:
        # 禁用模式命中是硬错误：即使其余锚点全对，D2 也要归零。
        dim2.checks[-1].score = 0.0
        dim2.checks[-1].detail += f"；禁用模式命中 {forbidden_count} 题（下标 {forbidden_hits}）"
    dim2.score = sum(c.score for c in dim2.checks)

    kp_hits = sum(
        1 for kp in case.knowledge_points
        if any(_kp_token_hit(kp, f"{_draft_text(d, 'stem')}\n{_draft_text(d, 'analysis')}") for d in drafts)
    )
    kp_ratio = kp_hits / max(1, len(case.knowledge_points))
    step_ratio = sum(step_ok_flags) / max(1, delivered)
    analysis_len_ratio = sum(analysis_len_flags) / max(1, delivered)
    dim3 = DimensionResult("D3", "教学性", 0.0, DIMENSION_MAX["D3_pedagogy"])
    dim3.checks.append(CheckResult(
        "D3a_steps", f"解析含步骤线索 {sum(step_ok_flags)}/{delivered}",
        DIMENSION_MAX["D3_pedagogy"] * 0.4 * step_ratio, DIMENSION_MAX["D3_pedagogy"] * 0.4,
        f"步骤线索比例 {step_ratio:.0%}", {"step_ratio": round(step_ratio, 4)},
    ))
    dim3.checks.append(CheckResult(
        "D3b_analysis_length", f"解析篇幅达标 {sum(analysis_len_flags)}/{delivered}",
        DIMENSION_MAX["D3_pedagogy"] * 0.3 * analysis_len_ratio, DIMENSION_MAX["D3_pedagogy"] * 0.3,
        f"达标比例 {analysis_len_ratio:.0%}（阈值 {case.min_analysis_chars} 字）",
        {"analysis_len_ratio": round(analysis_len_ratio, 4)},
    ))
    dim3.checks.append(CheckResult(
        "D3c_knowledge_points", f"知识点进入题目 {kp_hits}/{len(case.knowledge_points)}",
        DIMENSION_MAX["D3_pedagogy"] * 0.3 * kp_ratio, DIMENSION_MAX["D3_pedagogy"] * 0.3,
        f"覆盖比例 {kp_ratio:.0%}", {"kp_ratio": round(kp_ratio, 4)},
    ))
    dim3.score = sum(c.score for c in dim3.checks)

    type_ratio = sum(type_cue_flags) / max(1, delivered)
    answer_form_ratio = sum(answer_form_flags) / max(1, delivered)
    dim4 = DimensionResult("D4", "题型契约", 0.0, DIMENSION_MAX["D4_contract"])
    dim4.checks.append(CheckResult(
        "D4a_type_cue", f"题面结构匹配 {case.question_type} {sum(type_cue_flags)}/{delivered}",
        DIMENSION_MAX["D4_contract"] * 0.5 * type_ratio, DIMENSION_MAX["D4_contract"] * 0.5,
        f"匹配比例 {type_ratio:.0%}", {"type_ratio": round(type_ratio, 4)},
    ))
    dim4.checks.append(CheckResult(
        "D4b_answer_form", f"答案形态匹配 {case.question_type} {sum(answer_form_flags)}/{delivered}",
        DIMENSION_MAX["D4_contract"] * 0.5 * answer_form_ratio, DIMENSION_MAX["D4_contract"] * 0.5,
        f"匹配比例 {answer_form_ratio:.0%}", {"answer_form_ratio": round(answer_form_ratio, 4)},
    ))
    dim4.score = sum(c.score for c in dim4.checks)

    card.dimensions.extend([dim1, dim2, dim3, dim4])

    if (case.evolution_evaluation or {}).get("solution_fingerprint"):
        penalty_rows: List[dict] = []
        for draft in drafts:
            supervision = draft.get("supervision_summary") if isinstance(draft.get("supervision_summary"), dict) else {}
            persisted = (
                supervision.get("evolution_penalties")
                if isinstance(supervision.get("evolution_penalties"), dict)
                else {}
            )
            persisted_imitation = (
                persisted.get("imitation") if isinstance(persisted.get("imitation"), dict) else {}
            )
            difficulty_evidence_count = int(supervision.get("difficulty_evidence_count") or 0)
            supervisor_evidence_count = int(persisted_imitation.get("supervisor_evidence_count") or 0)
            penalty_rows.append(
                evaluate_evolution_penalties(
                    draft=draft,
                    target_difficulty=case.difficulty,
                    assessed_difficulty=supervision.get("difficulty_estimate"),
                    difficulty_evidence=[True] * difficulty_evidence_count,
                    evaluation=case.evolution_evaluation,
                    supervisor_similarity=float(persisted_imitation.get("supervisor_similarity") or 0.0),
                    supervisor_similarity_evidence=[True] * supervisor_evidence_count,
                    supervisor_matched_ids=persisted_imitation.get("supervisor_matched_ids") or [],
                )
            )
        divisor = max(1, len(penalty_rows))
        difficulty_points = sum(float(row["difficulty"]["penalty"]) for row in penalty_rows) * 100 / divisor
        imitation_points = sum(float(row["imitation"]["penalty"]) for row in penalty_rows) * 100 / divisor
        similarities = [float(row["imitation"]["similarity"]) for row in penalty_rows]
        gaps = [int(row["difficulty"]["gap"]) for row in penalty_rows]
        card.evolution_penalties.extend(
            [
                PenaltyResult(
                    "EP_difficulty_mismatch",
                    "难度不匹配惩戒",
                    difficulty_points,
                    24.0,
                    f"平均难度等级差 {sum(gaps) / divisor:.2f}，扣 {difficulty_points:.1f} 分",
                    {"gaps": gaps},
                ),
                PenaltyResult(
                    "EP_solution_imitation",
                    "解法过程过度模仿惩戒",
                    imitation_points,
                    30.0,
                    (
                        f"最高抽象解法指纹相似度 {max(similarities, default=0.0):.1%}，"
                        f"阈值 {float(case.evolution_evaluation.get('max_solution_similarity') or 0.58):.1%}，"
                        f"扣 {imitation_points:.1f} 分"
                    ),
                    {"similarities": [round(value, 4) for value in similarities]},
                ),
            ]
        )

    # 过程诊断（不计分）：生成链路自评。
    verdicts = [str(((d.get("review") or {}).get("verdict")) or "").strip() for d in drafts]
    self_scores = [((d.get("review") or {}).get("overall_score") or 0) for d in drafts]
    card.process_diagnostics.append(CheckResult(
        "P1_pipeline_self_review", "生成链路自评（不计分）", 0.0, 0.0,
        f"verdict={verdicts or '无'}；自评分={self_scores or '无'}",
        {"verdicts": verdicts, "self_scores": self_scores},
    ))

    min_delivered = max(1, math.ceil(requested * _DELIVERY_COUNT_RATIO))
    delivery_ok = delivered >= min_delivered and sections_ratio >= _DELIVERY_COUNT_RATIO
    card.quality_gates.append(QualityGateResult(
        "GQ_delivery", "交付下限", delivery_ok, _DELIVERY_GATE_CEILING,
        f"交付 {delivered}/{requested}（下限 {min_delivered}）；三段完整 {sections_ratio:.0%}",
        {"delivered": delivered, "min_delivered": min_delivered, "sections_ratio": round(sections_ratio, 4)},
    ))
    correctness_ok = anchor_ratio >= _CORRECTNESS_RATIO and forbidden_count == 0
    card.quality_gates.append(QualityGateResult(
        "GQ_correctness", "正确性下限", correctness_ok, _CORRECTNESS_GATE_CEILING,
        f"锚点命中 {anchor_ratio:.0%}（阈值 {_CORRECTNESS_RATIO:.0%}）；禁用模式命中 {forbidden_count}",
        {"anchor_ratio": round(anchor_ratio, 4), "forbidden_hits": forbidden_hits},
    ))
    return card


def render_report(card: QuestionScorecard) -> str:
    lines: List[str] = []
    lines.append(f"# 出题 benchmark 报告：{card.title}（{card.case_id}）")
    lines.append("")
    lines.append(f"- 最终成熟度分：**{card.total:.1f} / {card.total_max:.0f}**（{card.readiness_level}）")
    lines.append(f"- 原始诊断分：**{card.raw_total:.1f} / {card.total_max:.0f}**")
    lines.append(
        f"- 进化惩戒前：**{card.pre_penalty_total:.1f}**；惩戒扣分：**{card.penalty_total:.1f}**"
    )
    lines.append(f"- 当前封顶：**{card.applied_ceiling:.1f}**（未通过门槛不能由无关加分抵消）")
    lines.append(f"- 评分版本：`{card.scoring_version}`")
    for note in card.notes:
        lines.append(f"- 备注：{note}")
    lines.append("")
    if card.evolution_penalties:
        lines.append("## 进化惩戒")
        lines.append("")
        for penalty in card.evolution_penalties:
            lines.append(
                f"- `{penalty.id}` {penalty.title}：**-{penalty.points:.1f}**（上限 {penalty.max_points:.0f}）— {penalty.detail}"
            )
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
    for dim in card.dimensions:
        lines.append(f"## {dim.dimension} {dim.title}（{dim.score:.1f}/{dim.max_score:.0f}）")
        lines.append("")
        for check in dim.checks:
            lines.append(f"- `{check.id}` {check.description}：**{check.score:.1f}**/{check.max_score:.0f} — {check.detail}")
        lines.append("")
    lines.append("## 过程诊断（不计入总分）")
    lines.append("")
    for check in card.process_diagnostics:
        lines.append(f"- `{check.id}` {check.description} — {check.detail}")
    lines.append("")
    return "\n".join(lines)
