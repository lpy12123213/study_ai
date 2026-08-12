"""Deterministic whole-document learning-loop contract inspection.

The author pipeline and the offline benchmark share the same learner-visible
contract: measurable objectives, prerequisites, worked examples, tiered practice,
and paired answers with scoring points.  Inspection is deliberately local and
deterministic; it does not call an LLM and ignores fenced code plus quoted archive
metadata so echoed generation requirements cannot satisfy the contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Pattern, Set

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

_OBJECTIVE_HEADING_RE = re.compile(r"(?:学习目标|学习成果|本章目标)")
_PREREQUISITE_HEADING_RE = re.compile(r"(?:前置知识|先修知识|学习前提)")
_QUESTION_HEADING_RE = re.compile(r"(?:自测题|练习题|巩固练习|章节练习|自我检测)")
_LEARNING_TAG_RE = re.compile(r"\[(EX|Q|A)(\d+)\]", re.IGNORECASE)


@dataclass(frozen=True)
class LearningContractRequirements:
    min_objectives: int = 3
    min_worked_examples: int = 2
    min_practice_questions: int = 6
    min_answered_questions: int = 6
    required_levels: List[str] = field(default_factory=lambda: ["基础", "应用", "迁移"])


def renumber_learning_tags_by_section(section_bodies: List[str]) -> List[str]:
    """Turn section-local EX/Q/A numbering into stable document-global numbering.

    Section writers work independently and commonly restart at ``1``. Examples
    have their own sequence; questions and answers share one mapping so every
    local ``Qn`` remains paired with the corresponding ``An`` after renumbering.
    """

    next_example = 1
    next_question = 1
    normalized: List[str] = []
    for raw_body in section_bodies:
        example_map: Dict[str, int] = {}
        question_map: Dict[str, int] = {}

        def _replace(match: "re.Match[str]") -> str:
            nonlocal next_example, next_question
            prefix = match.group(1).upper()
            local_id = match.group(2)
            if prefix == "EX":
                if local_id not in example_map:
                    example_map[local_id] = next_example
                    next_example += 1
                return f"[EX{example_map[local_id]}]"
            if local_id not in question_map:
                question_map[local_id] = next_question
                next_question += 1
            return f"[{prefix}{question_map[local_id]}]"

        normalized.append(_LEARNING_TAG_RE.sub(_replace, str(raw_body or "")))
    return normalized


def _without_fenced_code(markdown: str) -> str:
    lines: List[str] = []
    in_fence = False
    for line in str(markdown or "").splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and not line.lstrip().startswith(">"):
            lines.append(line)
    return "\n".join(lines)


def _section_bodies(markdown: str, title_pattern: Pattern[str]) -> List[str]:
    """Return all matching heading bodies, not only the first one.

    Generated books commonly place practice and answers inside each chapter.
    Aggregating all matching sections prevents a valid distributed learning loop
    from being hidden by the first chapter's local exercise block.
    """

    lines = str(markdown or "").splitlines()
    matches: List[tuple[int, int]] = []
    in_fence = False
    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = _HEADING_RE.match(line)
        if heading and title_pattern.search(heading.group(2)):
            matches.append((index + 1, len(heading.group(1))))

    bodies: List[str] = []
    for start, level in matches:
        end = len(lines)
        in_fence = False
        for index in range(start, len(lines)):
            line = lines[index]
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            heading = _HEADING_RE.match(line)
            if heading and len(heading.group(1)) <= level:
                end = index
                break
        bodies.append("\n".join(lines[start:end]).strip())
    return bodies


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


def inspect_learning_contract(
    markdown: str,
    requirements: LearningContractRequirements | None = None,
) -> Dict[str, Any]:
    """Inspect a complete Markdown book and return metrics plus missing items."""

    req = requirements or LearningContractRequirements()
    text = _without_fenced_code(markdown)

    objective_text = "\n".join(_section_bodies(text, _OBJECTIVE_HEADING_RE))
    objective_count = len(_LIST_ITEM_RE.findall(objective_text))
    prerequisite_text = "\n".join(_section_bodies(text, _PREREQUISITE_HEADING_RE))
    prerequisites_ok = len(re.sub(r"\s+", "", prerequisite_text)) >= 12

    worked_examples = _worked_example_count(text)
    question_ids = set(_QUESTION_TAG_RE.findall(text))
    question_sections = "\n".join(_section_bodies(text, _QUESTION_HEADING_RE))
    fallback_questions = len(_QUESTION_LINE_RE.findall(question_sections)) if question_sections else 0
    question_count = max(len(question_ids), fallback_questions)
    level_hits = [level for level in req.required_levels if f"[{level}]" in text]

    answer_ids = set(_ANSWER_TAG_RE.findall(text))
    paired_ids = question_ids & answer_ids
    rubric_ok = bool(_RUBRIC_CUE_RE.search(text))
    missing_answers = sorted(question_ids - answer_ids, key=lambda value: int(value))

    missing: List[str] = []
    if objective_count < req.min_objectives:
        missing.append(f"可检验学习目标 {objective_count}/{req.min_objectives}")
    if not prerequisites_ok:
        missing.append("前置知识小节缺失或内容过空")
    if worked_examples < req.min_worked_examples:
        missing.append(f"带步骤例题 {worked_examples}/{req.min_worked_examples}")
    if question_count < req.min_practice_questions:
        missing.append(f"自测题 {question_count}/{req.min_practice_questions}")
    absent_levels = [level for level in req.required_levels if level not in level_hits]
    if absent_levels:
        missing.append("自测层级缺少 " + "、".join(absent_levels))
    if len(paired_ids) < req.min_answered_questions:
        missing.append(f"Q/A 对应 {len(paired_ids)}/{req.min_answered_questions}")
    if not rubric_ok:
        missing.append("答案缺少评分点")

    return {
        "passed": not missing,
        "missing": missing,
        "objective_count": objective_count,
        "prerequisites_ok": prerequisites_ok,
        "worked_examples": worked_examples,
        "question_count": question_count,
        "question_ids": sorted(question_ids, key=int),
        "answer_ids": sorted(answer_ids, key=int),
        "paired_count": len(paired_ids),
        "level_hits": level_hits,
        "rubric_ok": rubric_ok,
        "missing_answers": missing_answers,
    }
