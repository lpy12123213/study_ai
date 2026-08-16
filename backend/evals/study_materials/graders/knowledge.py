"""知识理解评分：K 维度。

标题与目录不算讲解；参考文献标题之后的内容也不参与知识命中。

- K1：事实锚点逐条匹配，并按事实所在段落是否带有效内联引用逐条门控。
- K2：正确关键词还必须与“误区/并非/而是”等纠错语境相邻。
- K3：两个术语除在小窗口共现外，还必须出现明确的对比语义。
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional

from backend.evals.study_materials.case_schema import BenchmarkCase, RequiredFact
from backend.evals.study_materials.graders.citations import valid_inline_citation_ids
from backend.evals.study_materials.graders.common import DIMENSION_MAX, CheckResult, DimensionResult, make_dimension

# (markdown, fact_description, source_urls) -> 是否满足事实点
LlmFactJudge = Callable[[str, str, List[str]], bool]

_CONTRAST_WINDOW = 800

# 无有效内联引用的事实仍保留 15%“草稿内容”分，但不能冒充可核验知识。
_TRACE_FLOOR = 0.15

_HEADING_LINE_RE = re.compile(r"^#{1,6}\s")
_TOC_HEADING_RE = re.compile(r"^#{2,4}\s*.*(知识点目录|目录)\s*$")
_REFERENCES_HEADING_RE = re.compile(
    r"^#{1,4}\s*(参考文献|参考资料|引用文献|引用来源|来源|References|Bibliography|Sources)\s*$",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^[-*+]\s")
_CORRECTION_CUE_RE = re.compile(
    r"误区|误解|易错|澄清|注意|并非|不是|不等于|不能|不可|而是|区别|混淆|切勿|不要|避免"
)
_CONTRAST_CUE_RE = re.compile(
    r"对比|比较|区别|不同|相同|相比|相较|而非|而是|前者|后者|vs\.?|versus",
    re.IGNORECASE,
)
_INLINE_FOOTNOTE_RE = re.compile(r"\[\^([^\]]+)\]")
_INLINE_NUMERIC_RE = re.compile(r"\[(\d{1,2})\]")
_CONDITIONAL_LABEL_RE = re.compile(r"^\s*P\(\s*(?P<event>.+?)\s*\|\s*(?P<condition>.+?)\s*\)\s*$", re.IGNORECASE)
_CONDITIONAL_EXPR_RE = re.compile(
    r"P\s*\(\s*(?P<event>[^()]{1,80}?)\s*(?:\\mid|\|)\s*(?P<condition>[^()]{1,80}?)\s*\)",
    re.IGNORECASE,
)


def _content_text(markdown: str) -> str:
    """剥离标题、目录 bullet 与参考文献后的正文，保留代码块内容。"""
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
            if _REFERENCES_HEADING_RE.match(stripped):
                break
            in_toc = bool(_TOC_HEADING_RE.match(stripped))
            continue
        if in_toc and _BULLET_RE.match(stripped):
            continue
        lines.append(line)
    # Markdown 中的百分号通常由 LaTeX 写成 ``\%``。用例事实契约按学习者
    # 实际看到的 ``%`` 编写；若不在评分入口归一化，已经正确写出的 15.4\%
    # 会被确定性正则误判为缺失。
    return "\n".join(lines).replace(r"\%", "%")


def _fact_passed(fact: RequiredFact, text: str) -> bool:
    match = fact.match
    for pattern in match.all:
        if not re.search(pattern, text, re.IGNORECASE):
            return False
    if match.any and not any(re.search(pattern, text, re.IGNORECASE) for pattern in match.any):
        return False
    return not any(re.search(pattern, text, re.IGNORECASE) for pattern in match.none)


def _valid_markers_in(text: str) -> set[str]:
    markers = {f"f:{value}" for value in _INLINE_FOOTNOTE_RE.findall(text)}
    markers.update(f"n:{value}" for value in _INLINE_NUMERIC_RE.findall(text))
    return markers


def _fact_trace_hit(fact: RequiredFact, text: str, valid_markers: set[str]) -> bool:
    if not valid_markers:
        return False
    # 输出契约要求“关键事实句后引用”；按段落/表格行定位，避免文档级引用漂移。
    chunks = [
        chunk.strip()
        for chunk in re.split(r"\n\s*\n|(?=^\s*\|)", text, flags=re.MULTILINE)
        if chunk.strip()
    ]
    return any(
        _fact_passed(fact, chunk) and bool(_valid_markers_in(chunk) & valid_markers)
        for chunk in chunks
    )


def _explicit_correction_hit(pattern: str, text: str) -> bool:
    for match in re.finditer(pattern, text, re.IGNORECASE):
        window = text[max(0, match.start() - 180): min(len(text), match.end() + 180)]
        if _CORRECTION_CUE_RE.search(window):
            return True
    return False


def _contrast_hit(pair: List[str], text: str) -> bool:
    if _reverse_conditional_hit(pair, text):
        return True
    a, b = pair[0].casefold(), pair[1].casefold()
    folded = text.casefold()
    for match in re.finditer(re.escape(a), folded):
        window = folded[
            max(0, match.start() - _CONTRAST_WINDOW // 2):
            match.end() + _CONTRAST_WINDOW // 2
        ]
        if b in window and _CONTRAST_CUE_RE.search(window):
            return True
    return False


def _conditional_label_parts(value: str) -> Optional[tuple[str, str]]:
    match = _CONDITIONAL_LABEL_RE.match(str(value or ""))
    if not match:
        return None
    return (match.group("event").strip().casefold(), match.group("condition").strip().casefold())


def _normalize_math_token(value: str) -> str:
    return re.sub(r"[\s{}]", "", str(value or "")).casefold()


def _reverse_conditional_hit(pair: List[str], text: str) -> bool:
    """Recognize an explicitly contrasted pair of reversed conditional probabilities.

    Benchmark labels may use learner-facing event names (``P(阳性|患病)``), while a
    correct generated book consistently uses symbols (``P(T^+\\mid D)``). Requiring
    literal label equality therefore rejects the exact mathematical contrast being
    tested. The special case is deliberately structural: the case labels themselves
    must be reversals, and the document must contain two nearby probability formulas
    whose event/condition positions are also reversed plus an explicit contrast cue.
    """

    if len(pair) != 2:
        return False
    left = _conditional_label_parts(pair[0])
    right = _conditional_label_parts(pair[1])
    if left is None or right is None or left != (right[1], right[0]):
        return False

    expressions = [
        (
            match.start(),
            match.end(),
            _normalize_math_token(match.group("event")),
            _normalize_math_token(match.group("condition")),
        )
        for match in _CONDITIONAL_EXPR_RE.finditer(text)
    ]
    for index, first in enumerate(expressions):
        for second in expressions[index + 1:]:
            if first[2:] != (second[3], second[2]):
                continue
            start = max(0, min(first[0], second[0]) - _CONTRAST_WINDOW // 2)
            end = min(len(text), max(first[1], second[1]) + _CONTRAST_WINDOW // 2)
            if _CONTRAST_CUE_RE.search(text[start:end]):
                return True
    return False


def grade_knowledge(
    case: BenchmarkCase,
    markdown: str,
    *,
    llm_judge: Optional[LlmFactJudge] = None,
    citation_ratio: float = 0.0,
) -> DimensionResult:
    """K 维度：事实、误区与辨析；事实溯源按段落逐条判定。"""
    dim = make_dimension("K")
    total_max = DIMENSION_MAX["K"]
    text = _content_text(markdown or "")
    valid_markers = valid_inline_citation_ids(markdown or "")

    facts = case.required_facts
    per_fact = (total_max * 0.6) / max(1, len(facts))
    passed_n = 0
    grounded_n = 0
    llm_rescued = 0
    failed_details: List[str] = []
    for fact in facts:
        deterministic_ok = _fact_passed(fact, text)
        ok = deterministic_ok
        if not ok and llm_judge is not None:
            try:
                ok = bool(llm_judge(text, fact.description, fact.source_urls))
                llm_rescued += 1 if ok else 0
            except Exception:  # noqa: BLE001 - judge 故障不拖垮评分
                ok = False
        passed_n += 1 if ok else 0
        grounded_n += 1 if deterministic_ok and _fact_trace_hit(fact, text, valid_markers) else 0
        if not ok:
            failed_details.append(fact.id)

    detail = "未命中: " + "、".join(failed_details) if failed_details else "全部命中"
    if llm_rescued:
        detail += f"（其中 {llm_rescued} 条经 LLM 复核通过）"
    detail += (
        f"；逐事实溯源 {grounded_n}/{passed_n or 0}；"
        f"文档 C2 比例 {max(0.0, min(1.0, citation_ratio)):.2f}"
    )
    k1_score = per_fact * (passed_n * _TRACE_FLOOR + grounded_n * (1.0 - _TRACE_FLOOR))
    dim.checks.append(CheckResult(
        "K1_facts",
        f"事实检查点 {passed_n}/{len(facts)} 命中（逐事实可溯源门控）",
        k1_score,
        total_max * 0.6,
        detail,
        metrics={
            "matched_count": passed_n,
            "grounded_count": grounded_n,
            "total": len(facts),
            "matched_ratio": round(passed_n / max(1, len(facts)), 4),
            "grounded_ratio": round(grounded_n / max(1, len(facts)), 4),
        },
    ))

    traps = case.traps
    trap_scores: List[float] = []
    trap_notes: List[str] = []
    for trap in traps:
        wrong_hit = bool(re.search(trap.wrong_pattern, text, re.IGNORECASE))
        correct_hit = bool(re.search(trap.correct_pattern, text, re.IGNORECASE))
        correction_hit = correct_hit and _explicit_correction_hit(trap.correct_pattern, text)
        score = 1.0 if correction_hit else 0.0
        trap_scores.append(score)
        if score == 0.0 and wrong_hit:
            trap_notes.append(f"{trap.id} 把误解写成事实或未在邻近语境纠正")
        elif score == 0.0 and correct_hit:
            trap_notes.append(f"{trap.id} 仅出现正确关键词，缺少明确纠错语境")
        elif score == 0.0:
            trap_notes.append(f"{trap.id} 未驳正")
    k2_max = total_max * 0.2
    k2 = k2_max * (sum(trap_scores) / max(1, len(trap_scores))) if traps else 0.0
    dim.checks.append(CheckResult(
        "K2_traps",
        "常见误解陷阱（须在明确纠错语境中驳正）",
        k2,
        k2_max,
        "；".join(trap_notes) if trap_notes else "全部明确驳正",
        metrics={"addressed_count": int(sum(trap_scores)), "total": len(traps)},
    ))

    contrasts = case.contrasts
    contrast_hits = sum(1 for pair in contrasts if _contrast_hit(pair, text))
    k3_max = total_max * 0.2
    k3 = k3_max * (contrast_hits / max(1, len(contrasts))) if contrasts else 0.0
    missed = [" vs ".join(pair) for pair in contrasts if not _contrast_hit(pair, text)]
    dim.checks.append(CheckResult(
        "K3_contrasts",
        f"概念辨析 {contrast_hits}/{len(contrasts)} 组含明确对比语义",
        k3,
        k3_max,
        ("未辨析: " + "、".join(missed)) if missed else "全部辨析",
        metrics={"contrast_count": contrast_hits, "total": len(contrasts)},
    ))
    return dim
