"""知识理解评分：K 维度。

判定前先经 ``_content_text`` 剥离标题行与目录 bullet——骨架文字（往往是
用户 query 的回显）不算"讲解"，防止空壳成稿靠标题蹭分。

- K1 事实检查点：用例锚定的正则确定性匹配；``llm_judge`` 开启时，
  确定性判定失败的检查点交 LLM 复核（语义表述可能不同），复核通过仍给分。
  K1 受**可溯源门控**：成稿没有内联引用时，事实点只按 ``_TRACE_FLOOR``
  的比例计分——benchmark 的立场是自学资料的关键论断必须可溯源。
- K2 陷阱：把常见误解写成事实且未驳正判 0；提到误解并驳正判满分；
  完全未触及同样判 0（用例指定的误解是合格讲义必须覆盖的）。
- K3 概念辨析：对比对必须在小窗口内共现（真正做了对比，而非各讲各的）。
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional

from backend.evals.study_materials.case_schema import BenchmarkCase, RequiredFact
from backend.evals.study_materials.graders.common import DIMENSION_MAX, CheckResult, DimensionResult, make_dimension

# (markdown, fact_description, source_urls) -> 是否满足事实点
LlmFactJudge = Callable[[str, str, List[str]], bool]

_CONTRAST_WINDOW = 800

# K1 可溯源门控下限：无任何内联引用时事实点只计 15%。
_TRACE_FLOOR = 0.15

_HEADING_LINE_RE = re.compile(r"^#{1,6}\s")
_TOC_HEADING_RE = re.compile(r"^#{2,4}\s*.*(知识点目录|目录)\s*$")
_BULLET_RE = re.compile(r"^[-*+]\s")


def _content_text(markdown: str) -> str:
    """剥离标题行与目录 bullet 后的正文文本。

    知识维度只应对正文判定：标题/目录里出现的概念名（往往来自用户 query 的
    原样回显）不代表资料真正讲解了它。代码块内容保留（可能含公式）。
    """
    lines: List[str] = []
    in_fence = False
    in_toc = False
    for line in (markdown or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            lines.append(line)
            continue
        if in_fence:
            lines.append(line)
            continue
        if _HEADING_LINE_RE.match(stripped):
            in_toc = bool(_TOC_HEADING_RE.match(stripped))
            continue
        if in_toc and _BULLET_RE.match(stripped):
            continue
        lines.append(line)
    return "\n".join(lines)


def _fact_passed(fact: RequiredFact, text: str) -> bool:
    match = fact.match
    for pattern in match.all:
        if not re.search(pattern, text, re.IGNORECASE):
            return False
    if match.any and not any(re.search(p, text, re.IGNORECASE) for p in match.any):
        return False
    return not any(re.search(p, text, re.IGNORECASE) for p in match.none)


def _trap_score(wrong_hit: bool, correct_hit: bool) -> float:
    if wrong_hit and not correct_hit:
        return 0.0  # 把误解写成了事实
    if correct_hit:
        return 1.0  # 明确给出正确论断（无论是否点名误解）
    return 0.0  # 未触及：用例指定的误解是合格讲义必须覆盖的


def _contrast_hit(pair: List[str], text: str) -> bool:
    a, b = pair[0].casefold(), pair[1].casefold()
    folded = text.casefold()
    for m in re.finditer(re.escape(a), folded):
        window = folded[max(0, m.start() - _CONTRAST_WINDOW // 2): m.end() + _CONTRAST_WINDOW // 2]
        if b in window:
            return True
    return False


def grade_knowledge(
    case: BenchmarkCase,
    markdown: str,
    *,
    llm_judge: Optional[LlmFactJudge] = None,
    citation_ratio: float = 0.0,
) -> DimensionResult:
    """K 维度：知识理解（满分 DIMENSION_MAX['K']）。

    ``citation_ratio`` 是 C2 内联引用得分比例（0..1，由 scorecard 注入），
    对 K1 做门控：无引用的"裸论断"事实点只按 _TRACE_FLOOR 计分。
    """
    dim = make_dimension("K")
    total_max = DIMENSION_MAX["K"]
    text = _content_text(markdown or "")
    trace_factor = _TRACE_FLOOR + (1.0 - _TRACE_FLOOR) * max(0.0, min(1.0, citation_ratio))

    facts = case.required_facts
    per_fact = (total_max * 0.6) / max(1, len(facts))
    passed_n = 0
    llm_rescued = 0
    failed_details: List[str] = []
    for fact in facts:
        ok = _fact_passed(fact, text)
        if not ok and llm_judge is not None:
            try:
                ok = bool(llm_judge(text, fact.description, fact.source_urls))
                llm_rescued += 1 if ok else 0
            except Exception:  # noqa: BLE001 - judge 故障不拖垮评分
                ok = False
        passed_n += 1 if ok else 0
        if not ok:
            failed_details.append(fact.id)
    detail = "未命中: " + "、".join(failed_details) if failed_details else "全部命中"
    if llm_rescued:
        detail += f"（其中 {llm_rescued} 条经 LLM 复核通过）"
    detail += f"；溯源系数 ×{trace_factor:.2f}（内联引用比例 {citation_ratio:.2f}）"
    dim.checks.append(CheckResult(
        "K1_facts", f"事实检查点 {passed_n}/{len(facts)} 命中（锚定学术来源，可溯源门控）",
        per_fact * passed_n * trace_factor, total_max * 0.6, detail,
    ))

    traps = case.traps
    trap_scores: List[float] = []
    trap_notes: List[str] = []
    for trap in traps:
        wrong_hit = bool(re.search(trap.wrong_pattern, text, re.IGNORECASE))
        correct_hit = bool(re.search(trap.correct_pattern, text, re.IGNORECASE))
        s = _trap_score(wrong_hit, correct_hit)
        trap_scores.append(s)
        if s == 0.0 and wrong_hit:
            trap_notes.append(f"{trap.id} 把误解写成事实")
        elif s == 0.0:
            trap_notes.append(f"{trap.id} 未驳正")
    k2_max = total_max * 0.2
    k2 = k2_max * (sum(trap_scores) / max(1, len(trap_scores))) if traps else 0.0
    dim.checks.append(CheckResult(
        "K2_traps", "常见误解陷阱（写错或未驳正均判 0）",
        k2, k2_max, "；".join(trap_notes) if trap_notes else "全部驳正",
    ))

    contrasts = case.contrasts
    contrast_hits = sum(1 for pair in contrasts if _contrast_hit(pair, text))
    k3_max = total_max * 0.2
    k3 = k3_max * (contrast_hits / max(1, len(contrasts))) if contrasts else 0.0
    missed = [" vs ".join(p) for p in contrasts if not _contrast_hit(p, text)]
    dim.checks.append(CheckResult(
        "K3_contrasts", f"概念辨析 {contrast_hits}/{len(contrasts)} 组在上下文窗口内真正对比",
        k3, k3_max, ("未辨析: " + "、".join(missed)) if missed else "全部辨析",
    ))
    return dim
