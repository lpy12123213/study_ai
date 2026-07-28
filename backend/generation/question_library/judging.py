from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any

from backend.core.settings import LESSON_PLAN_MODEL
from backend.generation.question_library.curriculum_context import curriculum_context_for_prompt
from backend.generation.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.generation.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.generation.question_library.intuition_practice import (
    normalize_intuition_packet,
    normalize_intuition_practice_config,
)
from backend.generation.question_library.subject_knowledge import get_subject_bank, infer_subject_family
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry


def _prompt(prompt_id: str) -> str:
    return create_default_prompt_registry().render(prompt_id).content


def _resolve_judge_model() -> str:
    raw = str(os.getenv("QUESTION_LIBRARY_JUDGE_MODEL") or "").strip()
    if raw:
        return raw
    return str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini"


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _contract_text(value: Any) -> str:
    """Canonicalize short labels and verbatim evidence without paraphrasing it.

    Review models commonly preserve the same excerpt while changing harmless
    Markdown/LaTeX wrappers, full-width punctuation, or subscript braces.  The
    former whitespace-only comparison rejected those equivalent spellings.  We
    deliberately stop at notation-level normalization: reordered or
    paraphrased claims still do not become grounded evidence.
    """

    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    replacements = {
        r"\leq": "≤",
        r"\geq": "≥",
        r"\neq": "≠",
        r"\times": "×",
        r"\cdot": "·",
        r"\infty": "∞",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    # Handle the most common simple TeX fractions before structural braces are
    # removed.  Nested fractions remain conservative and must still be quoted
    # in the same notation by the reviewer.
    for _ in range(2):
        text = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"\1/\2", text)
    text = re.sub(r"\\(?:left|right|quad|qquad)\b|\\[,!;]", "", text)
    text = re.sub(r"\\(?:mathrm|text|operatorname)\s*\{([^{}]*)\}", r"\1", text)
    # Keep mathematical operators, letters/digits, and CJK text.  Removing
    # wrappers makes S_{3}=S_{9}, $S_3 = S_9$, and S3=S9 equivalent while still
    # requiring one normalized excerpt to be contiguous in the final artefact.
    return re.sub(r"[^0-9a-z\u4e00-\u9fff=<>\u2264\u2265\u2260+−\-*/^|·×∞]+", "", text)


def _mapping_value(mapping: Any, *aliases: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    normalized = {
        re.sub(r"[^a-z0-9]", "", str(key or "").lower()): value
        for key, value in mapping.items()
    }
    for alias in aliases:
        key = re.sub(r"[^a-z0-9]", "", str(alias or "").lower())
        if key in normalized and normalized[key] is not None:
            return normalized[key]
    return None


def _is_true(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "pass", "passed", "是", "通过"}
    return False


def _evidence_values(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [item for nested in value for item in _evidence_values(nested)]
    if isinstance(value, dict):
        nested = _mapping_value(
            value,
            "quote",
            "text",
            "excerpt",
            "evidence",
            "stem_evidence",
            "analysis_evidence",
            "question_quote",
            "solution_quote",
        )
        return _evidence_values(nested)
    text = str(value or "").strip()
    return [text] if text else []


def _evidence_is_grounded(evidence: Any, source: str) -> bool:
    normalized_source = _contract_text(source)
    for item in _evidence_values(evidence):
        quoted = _contract_text(item)
        if len(quoted) >= 2 and quoted in normalized_source:
            return True

        # A reviewer may compact several exact excerpts with an explicit
        # ellipsis.  Treat that as a compound quotation, not as fuzzy matching:
        # at least two substantial fragments must occur verbatim (after the
        # notation-only normalization above), in the same order, in the final
        # artefact.  A free paraphrase in any substantial fragment fails the
        # entire claim.
        raw_fragments = re.split(r"(?:\.{3,}|…+|⋯+)", str(item or ""))
        if len(raw_fragments) < 2:
            continue
        fragments = [
            fragment
            for fragment in (_contract_text(part) for part in raw_fragments)
            if len(fragment) >= 4
        ]
        if len(fragments) < 2:
            continue
        cursor = 0
        all_grounded = True
        for fragment in fragments:
            position = normalized_source.find(fragment, cursor)
            if position < 0:
                all_grounded = False
                break
            cursor = position + len(fragment)
        if all_grounded:
            return True
    return False


def _label_matches(expected: str, actual: str) -> bool:
    left = _contract_text(expected)
    right = _contract_text(actual)
    return bool(left and right and (left in right or right in left))


def _label_is_lexically_grounded(label: Any, source: str) -> bool:
    """Conservatively ground a string-only knowledge-point assertion.

    Some models return ``knowledge_points_used`` as the requested names rather
    than nested evidence objects.  A name can be accepted only when the outer
    semantic gate already says the request is aligned *and* the final artefact
    contains the concept (allowing small connective gaps such as
    ``等差数列 {a_n} 的前 n 项和``).  This is not a semantic
    substitute for the reviewer; it is an auditable lexical corroboration.
    """

    expected = _contract_text(label)
    actual = _contract_text(source)
    if len(expected) < 2 or not actual:
        return False
    if expected in actual:
        return True
    reduced = re.sub(r"(?:的)?(?:基本)?(?:性质|概念|定义|公式|方法|应用|规律|知识点)$", "", expected)
    if len(reduced) >= 4 and reduced in actual:
        return True
    grams = {
        expected[index : index + 2]
        for index in range(len(expected) - 1)
        if "的" not in expected[index : index + 2]
    }
    if len(grams) < 2:
        return False
    matched = sum(1 for gram in grams if gram in actual)
    return matched >= 2 and matched / len(grams) >= 0.6


_COMPARISON_MARKERS = (
    "比较",
    "对比",
    "评析",
    "评价",
    "权衡",
    "选择",
    "哪种",
    "哪一种",
    "优劣",
    "异同",
    "更自然",
    "更合适",
    "compare",
    "contrast",
    "evaluate",
    "choose",
    "which",
)
_SOLUTION_ROUTE_MARKERS = (
    "解法",
    "方法",
    "思路",
    "方案",
    "路径",
    "表征",
    "证明",
    "模型",
    "证据",
    "approach",
    "method",
    "solution",
    "representation",
    "proof",
    "model",
    "evidence",
)


def _stem_has_solution_comparison_contract(stem: str) -> bool:
    compact = re.sub(r"\s+", "", str(stem or "")).lower()
    return any(marker in compact for marker in _COMPARISON_MARKERS) and any(
        marker in compact for marker in _SOLUTION_ROUTE_MARKERS
    )


def _analysis_has_concrete_comparison(analysis: str) -> bool:
    compact = re.sub(r"\s+", "", str(analysis or "")).lower()
    markers = (
        "相比",
        "相较",
        "而",
        "但",
        "更",
        "直接",
        "简洁",
        "清晰",
        "自然",
        "直观",
        "统一",
        "迁移",
        "可见",
        "揭示",
        "边界",
        "whereas",
        "while",
        "better",
        "direct",
        "clear",
        "econom",
        "transfer",
        "visible",
    )
    return any(marker in compact for marker in markers)


def _comparison_criterion_is_concrete(value: Any) -> bool:
    criterion = _contract_text(value)
    if len(criterion) < 3:
        return False
    return criterion not in {
        "比较",
        "不同",
        "优劣",
        "方法",
        "两种方法",
        "各有特点",
        "compare",
        "different",
        "methods",
    }


def _coerce_alignment_items(
    value: Any,
    *,
    label_field: str,
    item_field_aliases: tuple[str, ...],
) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str):
        return [value]
    if not isinstance(value, dict):
        return []
    if any(_mapping_value(value, alias) is not None for alias in item_field_aliases):
        return [value]
    items: list[dict] = []
    for label, payload in value.items():
        if isinstance(payload, dict):
            item = dict(payload)
            item.setdefault(label_field, label)
        else:
            item = {label_field: label, "evidence": payload, "_implicit_used": True}
        items.append(item)
    return items


def _request_contract_alignment(
    draft: dict,
    spec: dict,
    source_pack: dict | None,
    review: dict,
) -> tuple[bool, list[str]]:
    """Verify that the final artefact, not its design notes, satisfies the request.

    The semantic reviewer remains responsible for necessity and must explicitly
    return ``request_aligned=true``.  The server corroborates that decision
    against the final artefact.  It accepts a small, audited set of common JSON
    aliases and notation-equivalent excerpts, but never fills a missing concept,
    route, goal, or comparison with design notes.
    """

    sp = source_pack if isinstance(source_pack, dict) else {}
    packet = (draft or {}).get("intuition_packet")
    packet = packet if isinstance(packet, dict) else {}
    requested_topic = str(
        sp.get("requested_topic") or sp.get("topic") or (spec or {}).get("topic") or ""
    ).strip()
    requested_knowledge_points = [
        str(item or "").strip()
        for item in (sp.get("knowledge_points") or (spec or {}).get("knowledge_points") or [])
        if str(item or "").strip()
    ]
    requested_config_input = sp.get("intuition_practice") or (spec or {}).get("intuition_practice")
    if not isinstance(requested_config_input, dict):
        requested_config_input = {"practice_goal": packet.get("practice_goal")}
    requested_config = normalize_intuition_practice_config(requested_config_input)
    requested_goal = str(requested_config.get("practice_goal") or "").strip()
    actual_goal = str(packet.get("practice_goal") or "").strip()
    issues: list[str] = []
    if actual_goal != requested_goal:
        issues.append("practice_goal_mismatch")

    semantic_request_alignment = _mapping_value(review, "request_aligned") is True
    alignment_value = _mapping_value(
        review,
        "request_alignment",
        "request_contract_alignment",
        "alignment",
    )
    alignment = alignment_value if isinstance(alignment_value, dict) else {}
    if not alignment and any(
        _mapping_value(review, key) is not None
        for key in (
            "topic_bindings",
            "topic_evidence",
            "knowledge_points_used",
            "knowledge_point_evidence",
            "goal_check",
            "practice_goal_check",
        )
    ):
        # Tolerate models that flatten the documented request_alignment object,
        # while applying the exact same evidence checks below.
        alignment = review
    if not alignment:
        return False, list(dict.fromkeys([*issues, "request_alignment_evidence_missing"]))

    stem = str((draft or {}).get("stem") or "")
    answer_analysis = "\n".join(
        (str((draft or {}).get("answer") or ""), str((draft or {}).get("analysis") or ""))
    )
    bindings_value = _mapping_value(
        alignment,
        "topic_bindings",
        "topic_binding",
        "topic_evidence",
        "topic_alignment",
        "requested_topic_bindings",
    )
    bindings = _coerce_alignment_items(
        bindings_value,
        label_field="requested_clause",
        item_field_aliases=(
            "requested_clause",
            "requested_topic_clause",
            "clause",
            "topic",
            "stem_evidence",
            "question_quote",
        ),
    )
    grounded_bindings = []
    for item in bindings:
        if not isinstance(item, dict):
            continue
        necessary_value = _mapping_value(item, "necessary", "is_necessary", "required", "essential")
        necessary = _is_true(necessary_value) or (
            necessary_value is None and semantic_request_alignment
        )
        if not necessary:
            continue
        requested_clause = str(
            _mapping_value(
                item,
                "requested_clause",
                "requested_topic_clause",
                "clause",
                "topic",
                "requested_topic",
            )
            or ""
        ).strip()
        if not requested_clause or not _label_matches(requested_topic, requested_clause):
            continue
        stem_evidence = _mapping_value(
            item,
            "stem_evidence",
            "question_evidence",
            "question_quote",
            "stem_quote",
            "prompt_evidence",
            "evidence",
            "quote",
            "excerpt",
        )
        if not _evidence_is_grounded(stem_evidence, stem):
            continue
        analysis_evidence = _mapping_value(
            item,
            "analysis_evidence",
            "solution_evidence",
            "reasoning_evidence",
            "analysis_quote",
            "solution_quote",
        )
        if analysis_evidence and not _evidence_is_grounded(analysis_evidence, answer_analysis):
            continue
        grounded_bindings.append(item)

    if requested_topic and not grounded_bindings:
        issues.append("requested_topic_not_grounded_in_stem")

    used_points_value = _mapping_value(
        alignment,
        "knowledge_points_used",
        "knowledge_point_usage",
        "knowledge_point_bindings",
        "knowledge_points",
        "knowledge_point_evidence",
    )
    used_points = _coerce_alignment_items(
        used_points_value,
        label_field="requested_knowledge_point",
        item_field_aliases=(
            "requested_knowledge_point",
            "knowledge_point",
            "requested_name",
            "name",
            "evidence",
            "stem_evidence",
            "analysis_evidence",
        ),
    )
    final_material = f"{stem}\n{answer_analysis}"
    for expected in requested_knowledge_points:
        expected_grounded = False
        for item in used_points:
            if isinstance(item, str):
                label = item
                necessary = semantic_request_alignment
                evidence_values: list[Any] = []
            elif isinstance(item, dict):
                label = str(
                    _mapping_value(
                        item,
                        "requested_knowledge_point",
                        "knowledge_point",
                        "requested_name",
                        "name",
                        "label",
                    )
                    or ""
                ).strip()
                necessary_value = _mapping_value(
                    item,
                    "necessary",
                    "is_necessary",
                    "required",
                    "essential",
                    "used",
                )
                necessary = _is_true(necessary_value) or (
                    necessary_value is None and semantic_request_alignment
                )
                evidence_values = [
                    value
                    for value in (
                        _mapping_value(item, "evidence", "grounded_evidence", "quote", "excerpt"),
                        _mapping_value(
                            item,
                            "stem_evidence",
                            "question_evidence",
                            "question_quote",
                            "stem_quote",
                        ),
                        _mapping_value(
                            item,
                            "analysis_evidence",
                            "solution_evidence",
                            "analysis_quote",
                            "solution_quote",
                        ),
                    )
                    if value is not None and _evidence_values(value)
                ]
            else:
                continue
            if not necessary or not _label_matches(expected, label):
                continue
            if evidence_values:
                expected_grounded = any(
                    _evidence_is_grounded(evidence, final_material) for evidence in evidence_values
                )
                if (
                    not expected_grounded
                    and semantic_request_alignment
                    and _contract_text(expected) == _contract_text(label)
                ):
                    # Some reviewers return a correct knowledge-point label but
                    # put provenance prose such as "（见分析证明2）" around the
                    # evidence instead of a contiguous quote.  Fall back only
                    # for an exact requested-label match under the explicit
                    # semantic gate, and still require the concept itself to be
                    # conservatively grounded in the final scored artefact.
                    expected_grounded = _label_is_lexically_grounded(label, final_material)
            else:
                # A string-only "used" assertion is accepted only under the
                # explicit semantic request-aligned gate and lexical grounding
                # in the final scored artefact.
                expected_grounded = semantic_request_alignment and _label_is_lexically_grounded(
                    label, final_material
                )
            if expected_grounded:
                break
        if not expected_grounded:
            issues.append(f"requested_knowledge_point_missing:{expected}")

    goal_check_value = _mapping_value(
        alignment,
        "goal_check",
        "practice_goal_check",
        "goal_alignment",
        "practice_goal_alignment",
    )
    goal_check = goal_check_value if isinstance(goal_check_value, dict) else {}
    if not goal_check and any(
        _mapping_value(alignment, key) is not None
        for key in ("practice_goal", "goal", "routes", "solution_routes", "comparison_criterion")
    ):
        goal_check = alignment
    goal_name = str(
        _mapping_value(goal_check, "practice_goal", "requested_practice_goal", "goal") or ""
    ).strip()
    goal_passed = _is_true(
        _mapping_value(goal_check, "passed", "goal_passed", "satisfied", "contract_passed")
    )
    if goal_name != requested_goal or not goal_passed:
        issues.append("practice_goal_contract_failed")
    if requested_goal == "solution_appreciation":
        if not _is_true(
            _mapping_value(
                goal_check,
                "non_mechanical_core",
                "non_mechanical",
                "core_non_mechanical",
                "structurally_non_mechanical",
            )
        ):
            issues.append("solution_appreciation_mechanical_core")
        routes_value = _mapping_value(
            goal_check,
            "routes",
            "solution_routes",
            "route_fingerprints",
            "methods",
            "approaches",
        )
        routes = _coerce_alignment_items(
            routes_value,
            label_field="representation",
            item_field_aliases=(
                "representation",
                "representation_type",
                "organizing_object",
                "organizing_idea",
                "decisive_move",
                "key_step",
                "analysis_evidence",
                "solution_quote",
            ),
        )
        signatures: list[str] = []
        grounded_routes = 0
        shared_stem_contract = _stem_has_solution_comparison_contract(stem)
        for route in routes[:4]:
            if not isinstance(route, dict):
                continue
            fields = [
                str(
                    _mapping_value(
                        route,
                        "representation",
                        "representation_type",
                        "route",
                        "route_name",
                        "method",
                        "approach",
                    )
                    or ""
                ).strip(),
                str(
                    _mapping_value(
                        route,
                        "organizing_object",
                        "organizing_idea",
                        "core_object",
                        "invariant",
                        "organizer",
                    )
                    or ""
                ).strip(),
                str(
                    _mapping_value(
                        route,
                        "decisive_move",
                        "decisive_step",
                        "key_move",
                        "key_step",
                        "critical_move",
                    )
                    or ""
                ).strip(),
            ]
            if not all(fields):
                continue
            stem_evidence = _mapping_value(
                route,
                "stem_evidence",
                "question_evidence",
                "question_quote",
                "stem_quote",
                "prompt_evidence",
            )
            stem_grounded = _evidence_is_grounded(stem_evidence, stem) or shared_stem_contract
            analysis_evidence = _mapping_value(
                route,
                "analysis_evidence",
                "solution_evidence",
                "reasoning_evidence",
                "analysis_quote",
                "solution_quote",
                "evidence",
                "quote",
                "excerpt",
            )
            analysis_grounded = _evidence_is_grounded(analysis_evidence, answer_analysis)
            if not analysis_evidence:
                analysis_grounded = any(
                    _evidence_is_grounded(field, answer_analysis) for field in fields
                )
            if not stem_grounded or not analysis_grounded:
                continue
            signatures.append("|".join(_contract_text(field) for field in fields))
            grounded_routes += 1
        if len(set(signatures)) < 2:
            issues.append("solution_routes_not_distinct_or_ungrounded")
        comparison_value = _mapping_value(
            goal_check,
            "comparison",
            "route_comparison",
            "evaluation",
        )
        comparison_mapping = comparison_value if isinstance(comparison_value, dict) else {}
        comparison_criterion = _mapping_value(
            goal_check,
            "comparison_criterion",
            "evaluation_criterion",
            "comparison_basis",
            "criterion",
            "basis",
        ) or _mapping_value(
            comparison_mapping,
            "comparison_criterion",
            "evaluation_criterion",
            "criterion",
            "basis",
        )
        comparison_evidence = _mapping_value(
            goal_check,
            "comparison_evidence",
            "evaluation_evidence",
            "comparison_quote",
            "justification",
        ) or _mapping_value(
            comparison_mapping,
            "comparison_evidence",
            "evaluation_evidence",
            "evidence",
            "quote",
            "justification",
        )
        if isinstance(comparison_value, str):
            comparison_criterion = comparison_criterion or comparison_value
            comparison_evidence = comparison_evidence or comparison_value
        comparison_grounded = _evidence_is_grounded(comparison_evidence, answer_analysis) or (
            _evidence_is_grounded(comparison_criterion, answer_analysis)
        )
        if not comparison_grounded and grounded_routes >= 2:
            # When the reviewer summarizes rather than quotes the comparison,
            # the final analysis itself still has to contain an evaluative
            # contrast.  Two independently grounded routes plus such language
            # are auditable evidence; route names in the mother stem are not.
            comparison_grounded = _analysis_has_concrete_comparison(answer_analysis)
        if not _comparison_criterion_is_concrete(comparison_criterion) or not comparison_grounded:
            issues.append("solution_comparison_not_grounded")

    return not issues, list(dict.fromkeys(issues))


def _mother_question_structural_depth(draft: dict, spec: dict) -> tuple[bool, list[str]]:
    """Apply narrow deterministic vetoes to plainly procedural mother questions.

    The LLM review remains useful for semantic judgments, but it must not be able
    to turn a routine exercise into an intuition task merely by describing the
    attached packet with words such as "symmetry" or "representation".  These
    checks therefore inspect the mother-question stem only, and intentionally
    target high-confidence recipe shapes rather than trying to estimate general
    mathematical elegance with keywords.

    The cross-subject solution-appreciation contract requires comparison to be
    part of the scored stem.  The math-specific veto remains narrow: a relation-
    led arithmetic-sequence problem (for example, one starting from equal partial
    sums or a pairing constraint) does not match it.  The rejected shape is the
    familiar parameter-recovery decomposition: two numeric terms are supplied,
    the learner is first asked for the general term, and a subsequent part asks
    for the partial sum or its extremum.
    """

    stem = str((draft or {}).get("stem") or "").strip()
    packet = (draft or {}).get("intuition_packet")
    packet = packet if isinstance(packet, dict) else {}
    practice_goal = str(packet.get("practice_goal") or "").strip().lower()
    subject = str((spec or {}).get("subject") or "").strip().lower()
    topic = str((spec or {}).get("topic") or "").strip().lower()
    if not stem:
        return (practice_goal != "solution_appreciation"), (
            ["solution_appreciation_missing_mother_question_comparison"]
            if practice_goal == "solution_appreciation"
            else []
        )

    compact = re.sub(r"\s+", "", stem).lower()
    issues: list[str] = []

    # A solution-appreciation packet cannot manufacture its learning objective
    # after a shallow mother question.  The scored stem itself must ask the
    # learner to compare/evaluate/select between solution representations.
    if practice_goal == "solution_appreciation":
        comparison_markers = (
            "比较",
            "对比",
            "评析",
            "评价",
            "权衡",
            "选择",
            "哪种",
            "哪一种",
            "优劣",
            "异同",
            "更自然",
            "更合适",
            "compare",
            "contrast",
            "evaluate",
            "choose",
            "which",
        )
        solution_route_markers = (
            "解法",
            "方法",
            "思路",
            "方案",
            "路径",
            "表征",
            "证明",
            "模型",
            "证据",
            "approach",
            "method",
            "solution",
            "representation",
            "proof",
            "model",
            "evidence",
        )
        asks_comparison = any(marker in compact for marker in comparison_markers)
        names_solution_routes = any(marker in compact for marker in solution_route_markers)
        if not (asks_comparison and names_solution_routes):
            issues.append("solution_appreciation_missing_mother_question_comparison")

    if not any(marker in subject for marker in ("数学", "math")):
        return not issues, issues

    arithmetic_sequence = "等差数列" in compact or "等差数列" in topic or "arithmeticsequence" in compact
    if not arithmetic_sequence:
        return not issues, issues

    # Accept a_1, a_{1}, and a1 notation.  Requiring a numeric right-hand side
    # distinguishes routine data recovery from a structural relation such as
    # a_p + a_q = a_r + a_s.
    supplied_numeric_terms = re.findall(
        r"a_?\{?\d+\}?=(?:[-+]?\d+(?:\.\d+)?|[-+]?\\frac\{?\d+\}?\{?\d+\}?)",
        compact,
    )
    has_two_numeric_terms = len(supplied_numeric_terms) >= 2
    # Match an already-supplied affine rule such as a_n=35-4n, a_{n}=-4n+35,
    # or a_n=n+2.  In this shape the arithmetic-sequence parameters and decisive
    # representation have already been exposed by the stem.
    has_explicit_affine_general_term = bool(
        re.search(
            r"a_?\{?n\}?=[-+]?(?:(?:\d+(?:\.\d+)?)?n(?:[-+]\d+(?:\.\d+)?)?|\d+(?:\.\d+)?[-+](?:\d+(?:\.\d+)?)?n)(?=[^a-z0-9_^]|$)",
            compact,
        )
    )
    asks_general_term = "通项" in compact or "generalterm" in compact
    mentions_partial_sum = "前n项和" in compact or bool(re.search(r"s_?\{?n\}?", compact))
    asks_sum_extremum = mentions_partial_sum and any(marker in compact for marker in ("最大", "最小", "最值"))
    if has_two_numeric_terms and asks_general_term and mentions_partial_sum:
        issues.append("routine_arithmetic_sequence_decomposition")
    if has_explicit_affine_general_term and asks_sum_extremum:
        issues.append("routine_explicit_general_term_sum_extremum")

    return not issues, issues


async def solve_draft(
    stem: str,
    options: dict,
    *,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    if not is_llm_configured():
        return {"match": False, "final_answer": "", "issues": ["llm_not_configured"], "summary": ""}

    subject = str((options or {}).get("subject") or "").strip()
    proposed_answer = str((options or {}).get("proposed_answer") or "").strip()
    family = infer_subject_family(subject)
    bank = get_subject_bank(subject)

    # Two-phase prompt: solve independently FIRST, then compare with proposed answer.
    # This avoids anchoring bias where the model confirms an incorrect proposed answer.
    payload = {
        "subject": subject,
        "stem": str(stem or "").strip(),
        "task": "First solve the problem completely and independently, including detailed derivation and the final answer. After solving, compare your result with the reference answer below and judge whether the reference answer is correct.",
        "proposed_answer": proposed_answer,
        "output_schema": {
            "solving_steps": "string (your complete solving process, including key derivation steps)",
            "final_answer": "string (the final answer you independently derived, in LaTeX)",
            "match": "bool (whether your answer is conclusion-equivalent to the reference answer)",
            "issues": "string[] (errors or inconsistencies in the reference answer; empty array if none)",
            "summary": "string (brief summary)",
        },
    }
    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    _prompt("question.solve.independent.v1")
                    + "\n\n"
                    f"<role>{str(bank.system_role or '').strip() or 'You are a rigorous problem-solving expert'}. Solve independently and do not be influenced by the reference answer.</role>\n"
                    "<task>\n"
                    "  <phase id='1'>Completely ignore the reference answer. Solve independently and write key derivation steps and the final answer.</phase>\n"
                    "  <phase id='2'>Compare your answer with the reference answer and judge whether the conclusions are equivalent.</phase>\n"
                    "</task>\n"
                    f"<subject_family>{family}</subject_family>\n"
                    "<subject_rules>\n"
                    "  <physics>Physics: model the process/analyze forces before setting equations; check directions, units, and dimensions.</physics>\n"
                    "  <chemistry>Chemistry: prioritize balanced equations and conservation; keep states and conditions complete.</chemistry>\n"
                    "  <chinese>Chinese: answers must closely follow textual evidence and question requirements with standard wording.</chinese>\n"
                    "  <english>English: locate evidence first, then provide a standard answer; grammar and discourse must be consistent.</english>\n"
                    "</subject_rules>\n"
                    "<match_criteria>\n"
                    "  If conclusions are equivalent, such as x=2 and \\(x=2\\), set match=true.\n"
                    "  If inconsistent, first check whether your own solution is wrong before making the final judgment.\n"
                    "</match_criteria>\n"
                    "<output_format>Output a strict JSON object only. Do not output Markdown or extra explanation.</output_format>"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=_resolve_judge_model() or "openai/gpt-5.4-mini",
        temperature=0.15,
        max_tokens=0,
        req_id_prefix="ql_solver",
        retries=2,
        raise_on_fail=False,
        stage_id="judge",
        stage_label="快速校验",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    match = bool(obj.get("match"))
    issues = obj.get("issues")
    return {
        "match": match,
        "final_answer": str(obj.get("final_answer") or "").strip(),
        "issues": list(issues or []) if isinstance(issues, list) else [],
        "summary": str(obj.get("summary") or "").strip(),
    }


async def check_ambiguity(
    draft: dict,
    *,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    if not is_llm_configured():
        return {"ambiguous": True, "issues": ["llm_not_configured"], "summary": ""}

    payload = {
        "stem": str((draft or {}).get("stem") or "").strip(),
        "answer": str((draft or {}).get("answer") or "").strip(),
        "output_schema": {
            "ambiguous": "bool (是否存在合理歧义/多解导致答案不唯一)",
            "issues": "string[]",
            "summary": "string",
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    _prompt("question.judge.ambiguity.v1")
                    + "\n\n"
                    "<role>You are a professional question-review expert specializing in ambiguity that may cause non-unique answers.</role>\n"
                    "<ambiguity_criteria>\n"
                    "  <rule>Set ambiguous=true only when the stem allows multiple reasonable interpretations that lead to different conclusions.</rule>\n"
                    "  <not_ambiguous>Case analysis itself is not ambiguity.</not_ambiguous>\n"
                    "  <not_ambiguous>Parameter-range discussion is not ambiguity.</not_ambiguous>\n"
                    "  <is_ambiguous>Mark ambiguous=true only when the stem cannot determine a unique answer path.</is_ambiguous>\n"
                    "</ambiguity_criteria>\n"
                    "<output_format>Output a strict JSON object only.</output_format>"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=_resolve_judge_model() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=0,
        req_id_prefix="ql_amb",
        retries=2,
        raise_on_fail=False,
        stage_id="judge",
        stage_label="快速校验",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    issues = obj.get("issues")
    return {
        "ambiguous": bool(obj.get("ambiguous")),
        "issues": list(issues or []) if isinstance(issues, list) else [],
        "summary": str(obj.get("summary") or "").strip(),
    }


async def quick_validate_draft(
    draft: dict,
    spec: dict,
    *,
    source_pack: dict | None = None,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    """Run the minimum safety gate required for a student self-practice packet.

    This deliberately avoids competition-style quality scoring, repeated solver
    consensus, and psychometric claims. One review call checks curriculum safety,
    correctness, packet alignment, and whether the task contains a genuine but
    syllabus-level structural decision instead of mechanical execution.
    """

    if not is_llm_configured():
        return {
            "pass": False,
            "scope_ok": False,
            "answer_correct": False,
            "answer_analysis_consistent": False,
            "conditions_sufficient": False,
            "unambiguous": False,
            "transfer_valid": False,
            "intuition_aligned": False,
            "structural_depth": False,
            "request_aligned": False,
            "issues": ["llm_not_configured"],
            "summary": "",
        }

    subject = str((spec or {}).get("subject") or (source_pack or {}).get("subject") or "").strip()
    curriculum = curriculum_context_for_prompt(source_pack or {})
    request_config = normalize_intuition_practice_config(
        (source_pack or {}).get("intuition_practice")
        or (spec or {}).get("intuition_practice")
        or {
            "practice_goal": ((draft or {}).get("intuition_packet") or {}).get("practice_goal")
            if isinstance((draft or {}).get("intuition_packet"), dict)
            else None
        }
    )
    packet = (draft or {}).get("intuition_packet")
    packet = packet if isinstance(packet, dict) else {}
    actual_goal = str(packet.get("practice_goal") or "").strip()
    if actual_goal != request_config["practice_goal"]:
        return {
            "pass": False,
            "scope_ok": False,
            "answer_correct": False,
            "answer_analysis_consistent": False,
            "conditions_sufficient": False,
            "unambiguous": False,
            "transfer_valid": False,
            "intuition_aligned": False,
            "structural_depth": False,
            "request_aligned": False,
            "issues": ["request_contract_mismatch", "practice_goal_mismatch"],
            "summary": "候选练习包改写了请求中的训练目标。",
            "overall_score": 0,
        }
    requested_knowledge_points = [
        str(item or "").strip()
        for item in (
            (source_pack or {}).get("knowledge_points")
            or (spec or {}).get("knowledge_points")
            or []
        )
        if str(item or "").strip()
    ]
    payload = {
        "subject": subject,
        "curriculum_context": curriculum,
        "request_contract": {
            "requested_topic": str(
                (source_pack or {}).get("requested_topic")
                or (source_pack or {}).get("topic")
                or (spec or {}).get("topic")
                or ""
            ).strip(),
            "requested_knowledge_points": requested_knowledge_points,
            "requested_practice_goal": request_config["practice_goal"],
            "requested_intuition_kinds": request_config["intuition_kinds"],
        },
        "question": {
            "stem": str((draft or {}).get("stem") or "").strip()[:2400],
            "answer": str((draft or {}).get("answer") or "").strip()[:2000],
            "analysis": str((draft or {}).get("analysis") or "").strip()[:3200],
            "intuition_packet": (draft or {}).get("intuition_packet")
            if isinstance((draft or {}).get("intuition_packet"), dict)
            else {},
        },
        "output_schema": {
            "scope_ok": "bool (all required knowledge and methods are in curriculum scope)",
            "answer_correct": "bool (independently checking the task leads to the proposed answer)",
            "answer_analysis_consistent": "bool",
            "conditions_sufficient": "bool",
            "unambiguous": "bool",
            "transfer_valid": "bool (the transfer stage preserves the decisive structure while changing at least two surface features, not only numbers)",
            "intuition_aligned": "bool (the stem, answer/analysis, intuition atom, and every required practice stage use the same decisive structure)",
            "structural_depth": "bool (the learner must independently notice or choose a decisive structure; the task is not direct formula substitution and does not fully specify the solution method)",
            "request_aligned": "bool (every requested topic/knowledge clause is necessary in the final mother task and the requested practice-goal contract passes)",
            "request_alignment": {
                "topic_bindings": [
                    {
                        "requested_clause": "string (echo the exact requested clause)",
                        "stem_evidence": "string (exact contiguous excerpt from the final stem)",
                        "analysis_evidence": "string (exact contiguous excerpt from answer/analysis, or empty)",
                        "necessary": "bool",
                    }
                ],
                "knowledge_points_used": [
                    {
                        "requested_knowledge_point": "string (echo the exact requested knowledge-point name)",
                        "evidence": "string (exact contiguous excerpt from stem/answer/analysis)",
                        "necessary": "bool",
                    }
                ],
                "goal_check": {
                    "practice_goal": "string (must equal requested_practice_goal)",
                    "passed": "bool",
                    "non_mechanical_core": "bool",
                    "routes": [
                        {
                            "representation": "string",
                            "organizing_object": "string",
                            "decisive_move": "string",
                            "stem_evidence": "string (exact contiguous excerpt requiring multiple routes; it may be the same shared comparison instruction for every route because the stem must not reveal route names in advance)",
                            "analysis_evidence": "string (exact contiguous excerpt)",
                        }
                    ],
                    "comparison_criterion": "string",
                    "comparison_evidence": "string (exact contiguous excerpt from answer/analysis)",
                },
            },
            "issues": "string[] (short, actionable issue codes or descriptions)",
            "summary": "string",
            "pass": "bool (true only when all nine checks above pass)",
        },
    }
    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    _prompt("question.judge.quality.v1")
                    + "\n\n"
                    "<role>You are a lightweight self-practice question checker.</role>\n"
                    "<scope>Check exactly nine gates: curriculum boundary, answer correctness, answer-analysis consistency, sufficient conditions, fatal ambiguity, valid transfer, intuition alignment, structural depth, and request alignment.</scope>\n"
                    "<independent_check>Briefly solve or verify each stage before comparing with the proposed answer. Use the scientific-compute tool only when it materially helps.</independent_check>\n"
                    "<intuition_alignment>\n"
                    "  <rule>intuition_aligned=true only when the stem's actual mathematical or disciplinary task, the answer and analysis, the atom's internal_model/decisive_cue/formal_anchor, and all required stage prompts and expected answers express the same decisive structure.</rule>\n"
                    "  <failure>If an atom or stage trains a different structure from the one needed to solve the stem, set intuition_aligned=false even when each part is separately correct.</failure>\n"
                    "</intuition_alignment>\n"
                    "<structural_depth>\n"
                    "  <rule>structural_depth=true only when the learner must independently notice, select, or test a decisive relation, representation, invariant, boundary, counterexample, causal model, or evidence pattern before routine execution.</rule>\n"
                    "  <failure>Set structural_depth=false when direct formula substitution suffices, when the stem fully names the method or complete sequence and leaves only mechanical work, or when the supposed transfer only replaces numbers.</failure>\n"
                    "  <routine_decomposition>A mother question that gives two numeric terms of an arithmetic sequence, first asks for its general term, and then asks for S_n or its extremum is routine parameter recovery, even if an attached packet later describes symmetry or compares methods. Set structural_depth=false.</routine_decomposition>\n"
                    "  <explicit_rule_routine>A mother question that already gives an affine arithmetic-sequence rule such as a_n=35-4n and asks for the extremum of S_n is routine execution. Asking for two methods or a comparison afterward does not make symmetry or an invariant necessary. Set structural_depth=false.</explicit_rule_routine>\n"
                    "  <low_entry>A short, low-entry, syllabus-level solution may pass when one non-obvious structural insight does the real work; do not demand long derivations or competition techniques.</low_entry>\n"
                    "  <appreciation>For practice_goal=solution_appreciation, require genuinely different solution paths that use different representations or organizing ideas and illuminate why the result is necessary; cosmetic algebraic rewrites do not pass.</appreciation>\n"
                    "  <appreciation_stem_contract>The mother-question stem itself must explicitly ask the learner to compare, evaluate, or choose between genuinely different solution paths or representations. An appreciation stage attached only in intuition_packet cannot upgrade a shallow scored question.</appreciation_stem_contract>\n"
                    "</structural_depth>\n"
                    "<request_alignment>\n"
                    "  <rule>Judge only the final stem, answer, analysis, and packet. Design notes cannot prove alignment. Every substantive requested-topic clause and requested knowledge point must be necessary to earn a scored mother-task answer, not merely mentioned in a hint, packet, or commentary.</rule>\n"
                    "  <evidence>For every claimed topic binding and requested knowledge point, echo the exact requested clause/name and quote an exact contiguous excerpt from the final stem, answer, or analysis. Set necessary=true only when omitting that disciplinary structure would prevent a complete scored answer.</evidence>\n"
                    "  <goal_match>The packet practice_goal must equal requested_practice_goal. Evaluate the selected goal by its own contract; do not replace it with a more convenient goal.</goal_match>\n"
                    "  <solution_appreciation>Require a non-mechanical core even before aesthetic commentary. Return at least two route fingerprints, each with representation, organizing_object, decisive_move, and grounded excerpts. The fingerprints must be genuinely different, and the comparison must cite a concrete criterion such as invariant visibility, economy, boundary clarity, unification, or transferability. The mother stem should require multiple routes without naming them in advance; therefore each route may use the same grounded stem_evidence excerpt for that shared requirement, while route-specific differences must be grounded separately in analysis_evidence.</solution_appreciation>\n"
                    "  <other_goals>fluency requires independent cue or representation selection; structural_intuition requires a hidden decisive structure; intuition_correction requires a plausible initial misjudgment plus discriminating evidence; transfer requires the same decisive structure under a changed relation, constraint, boundary, or representation.</other_goals>\n"
                    "</request_alignment>\n"
                    "<not_required>Do not score novelty, competition difficulty, discrimination, elegance, or psychometrics.</not_required>\n"
                    "<ambiguity>Case discussion and open reflection are not ambiguity when the allowed response space and reference criteria are clear.</ambiguity>\n"
                    "<pass_rule>pass=true only if scope_ok, answer_correct, answer_analysis_consistent, conditions_sufficient, unambiguous, transfer_valid, intuition_aligned, structural_depth, and request_aligned are all true.</pass_rule>\n"
                    "<output_format>Output one strict JSON object only.</output_format>"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=_resolve_judge_model(),
        temperature=0.1,
        max_tokens=0,
        req_id_prefix="ql_judge",
        retries=2,
        raise_on_fail=False,
        stage_id="judge",
        stage_label="快速校验",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    legacy_pass = bool(obj.get("pass"))

    def _legacy_flag(name: str) -> bool:
        return bool(obj.get(name)) if name in obj else legacy_pass

    def _required_flag(name: str) -> bool:
        # The two quality gates were added specifically to stop legacy `pass=true`
        # payloads from accepting shallow or internally mismatched packets.
        return obj.get(name) is True if name in obj else False

    flags = {
        "scope_ok": _legacy_flag("scope_ok"),
        "answer_correct": _legacy_flag("answer_correct"),
        "answer_analysis_consistent": _legacy_flag("answer_analysis_consistent"),
        "conditions_sufficient": _legacy_flag("conditions_sufficient"),
        "unambiguous": _legacy_flag("unambiguous"),
        "transfer_valid": _legacy_flag("transfer_valid"),
        "intuition_aligned": _required_flag("intuition_aligned"),
        "structural_depth": _required_flag("structural_depth"),
        "request_aligned": _required_flag("request_aligned"),
    }
    mother_depth_ok, mother_depth_issues = _mother_question_structural_depth(draft, spec)
    # Fail closed: semantic review may reject more cases, but it cannot override a
    # deterministic high-confidence routine-mother-question veto.
    flags["structural_depth"] = flags["structural_depth"] and mother_depth_ok
    request_contract_ok, request_contract_issues = _request_contract_alignment(
        draft,
        spec,
        source_pack,
        obj,
    )
    flags["request_aligned"] = flags["request_aligned"] and request_contract_ok
    issues = [str(item or "").strip() for item in (obj.get("issues") or []) if str(item or "").strip()]
    issue_by_flag = {
        "scope_ok": "out_of_scope",
        "answer_correct": "answer_incorrect",
        "answer_analysis_consistent": "answer_analysis_mismatch",
        "conditions_sufficient": "conditions_insufficient",
        "unambiguous": "fatal_ambiguity",
        "transfer_valid": "transfer_invalid",
        "intuition_aligned": "intuition_mismatch",
        "structural_depth": "structural_depth_insufficient",
        "request_aligned": "request_contract_mismatch",
    }
    required_issues = [issue_by_flag[name] for name, ok in flags.items() if not ok]
    issues = list(
        dict.fromkeys([*required_issues, *mother_depth_issues, *request_contract_issues, *issues])
    )
    passed = all(flags.values())
    return {
        "pass": passed,
        **flags,
        "issues": issues[:12],
        "summary": str(obj.get("summary") or "").strip(),
        "overall_score": 100 if passed else 0,
    }


async def judge_draft(
    draft: dict,
    spec: dict,
    *,
    source_pack: dict | None = None,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    if not is_llm_configured():
        return {"pass": False, "overall_score": 0, "issues": ["llm_not_configured"], "summary": ""}

    subject = str((spec or {}).get("subject") or "").strip()
    difficulty = str((spec or {}).get("difficulty") or "").strip()
    family = infer_subject_family(subject)
    bank = get_subject_bank(subject)
    requirements = (
        f"Target difficulty: {difficulty or 'medium-hard'}. The question must be novel, discriminative, and follow the reasoning structure in spec: "
        f"{str((spec or {}).get('reasoning') or '').strip()}。"
    )
    curriculum = curriculum_context_for_prompt(source_pack or {})
    curriculum_requirements = [str(x or "").strip() for x in (curriculum.get("question_requirements") or []) if str(x or "").strip()]
    if curriculum_requirements:
        requirements += " 新课标出题要求：" + "；".join(curriculum_requirements[:8]) + "。"
    in_scope = list((curriculum.get("knowledge_scope") or {}).get("in_scope") or [])
    out_of_scope = list((curriculum.get("knowledge_scope") or {}).get("out_of_scope") or [])
    if in_scope:
        requirements += " 知识范围应覆盖：" + "、".join(in_scope[:8]) + "。"
    if out_of_scope:
        requirements += " 不得涉及：" + "、".join(out_of_scope[:6]) + "。"
    prerequisites = [str(x or "").strip() for x in (curriculum.get("prerequisites") or []) if str(x or "").strip()]
    if prerequisites:
        requirements += " 前置知识假定：" + "、".join(prerequisites[:8]) + "。"

    extra_dims = []
    extra_dim_tags = ""
    if family == "physics":
        extra_dims = [{"name": "物理过程分析", "score": "int 1-10", "comment": "string"}]
        extra_dim_tags = "  <dim name='物理过程分析'>过程建模/受力分析/量纲单位是否正确，物理意义是否自洽</dim>\n"
    elif family == "chemistry":
        extra_dims = [{"name": "化学原理正确性", "score": "int 1-10", "comment": "string"}]
        extra_dim_tags = "  <dim name='化学原理正确性'>原理正确、配平规范、状态条件完整，守恒关系正确</dim>\n"
    elif family == "biology":
        extra_dims = [{"name": "证据链与实验设计", "score": "int 1-10", "comment": "string"}]
        extra_dim_tags = "  <dim name='证据链与实验设计'>推断是否基于材料证据；实验题是否体现对照与变量控制</dim>\n"
    elif family == "chinese":
        extra_dims = [{"name": "文本证据与表述", "score": "int 1-10", "comment": "string"}]
        extra_dim_tags = "  <dim name='文本证据与表述'>答案是否引用/依托文本证据，表述是否规范、分点清晰</dim>\n"
    elif family == "english":
        extra_dims = [{"name": "语篇依据与语言准确", "score": "int 1-10", "comment": "string"}]
        extra_dim_tags = "  <dim name='语篇依据与语言准确'>定位依据是否充分；语法/表达是否准确规范</dim>\n"

    payload = {
        "subject": subject,
        "requirements": requirements,
        "curriculum_context": curriculum,
        "spec": {
            "skill": str((spec or {}).get("skill") or "").strip(),
            "reasoning": str((spec or {}).get("reasoning") or "").strip(),
            "trap": str((spec or {}).get("trap") or "").strip(),
            "surface": str((spec or {}).get("surface") or "").strip(),
        },
        "question": {
            "stem": str((draft or {}).get("stem") or "").strip()[:1600],
            "answer": str((draft or {}).get("answer") or "").strip()[:1200],
            "analysis": str((draft or {}).get("analysis") or "").strip()[:2000],
        },
        "output_schema": {
            "verdict": "string (好题|普通题|差题)",
            "overall_score": "int 0-100",
            "dimensions": [
                {"name": "思维含量", "score": "int 1-10", "comment": "string"},
                {"name": "区分度", "score": "int 1-10", "comment": "string"},
                {"name": "知识覆盖", "score": "int 1-10", "comment": "string"},
                {"name": "表述规范", "score": "int 1-10", "comment": "string"},
                {"name": "创新性", "score": "int 1-10", "comment": "string"},
                {"name": "答案解析自洽", "score": "int 1-10", "comment": "string"},
                *extra_dims,
            ],
            "highlights": "string[]",
            "issues": "string[]",
            "summary": "string",
            "difficulty_estimate": "string (简单|中等|偏难|困难)",
            "novelty_score": "int 1-10",
            "reasoning_depth": "int 1-10",
            "pass": "bool",
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    _prompt("question.judge.quality.v1")
                    + "\n\n"
                    f"<role>{str(bank.system_role or '').strip() or 'You are a senior high-school curriculum researcher'}. Evaluate question quality by college-entrance-exam review standards and score objectively.</role>\n"
                    "<scoring_dimensions>\n"
                    "  <dim name='reasoning_depth'>Requires multi-step reasoning or strategic choices, not mechanical formula substitution.</dim>\n"
                    "  <dim name='discrimination'>Distinguishes students at different levels and is not a disguised textbook example.</dim>\n"
                    "  <dim name='knowledge_coverage'>Uses core concepts deeply and has a valuable assessment angle.</dim>\n"
                    "  <dim name='wording_standard'>The stem is clear, LaTeX is correct, and conditions are sufficient and unambiguous.</dim>\n"
                    "  <dim name='novelty'>Not a direct textbook example; includes new constraints or concept combinations.</dim>\n"
                    "  <dim name='answer_analysis_consistency'>Every derivation step is correct and the conclusion exactly matches the answer field.</dim>\n"
                    f"{extra_dim_tags}"
                    "</scoring_dimensions>\n"
                    "<pass_criteria>overall_score >= 70, answer_analysis_consistency >= 7, and reasoning_depth >= 6.</pass_criteria>\n"
                    "<output_format>Output a strict JSON object only. Do not output Markdown or explanations.</output_format>"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=0,
        req_id_prefix="ql_judge",
        retries=3,
        raise_on_fail=False,
        stage_id="judge",
        stage_label="快速校验",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    issues = obj.get("issues")
    dims = obj.get("dimensions")
    return {
        "pass": bool(obj.get("pass")),
        "verdict": str(obj.get("verdict") or "").strip(),
        "overall_score": _coerce_int(obj.get("overall_score"), 0),
        "dimensions": list(dims or []) if isinstance(dims, list) else [],
        "highlights": list(obj.get("highlights") or []) if isinstance(obj.get("highlights"), list) else [],
        "issues": list(issues or []) if isinstance(issues, list) else [],
        "summary": str(obj.get("summary") or "").strip(),
        "difficulty_estimate": str(obj.get("difficulty_estimate") or "").strip(),
        "novelty_score": _coerce_int(obj.get("novelty_score"), 0),
        "reasoning_depth": _coerce_int(obj.get("reasoning_depth"), 0),
    }


async def refine_draft(
    draft: dict,
    judge: dict,
    *,
    spec: dict | None = None,
    source_pack: dict | None = None,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    if not is_llm_configured():
        return dict(draft or {})

    issues = judge.get("issues") if isinstance(judge, dict) else []
    sp = source_pack if isinstance(source_pack, dict) else {}
    spec_data = spec if isinstance(spec, dict) else {}
    existing_packet = (
        (draft or {}).get("intuition_packet")
        if isinstance((draft or {}).get("intuition_packet"), dict)
        else {}
    )
    requested_config_input = sp.get("intuition_practice") or spec_data.get("intuition_practice")
    if not isinstance(requested_config_input, dict):
        requested_config_input = existing_packet
    requested_config = normalize_intuition_practice_config(requested_config_input)
    requested_topic = str(
        sp.get("requested_topic") or sp.get("topic") or spec_data.get("topic") or ""
    ).strip()
    payload = {
        "request_contract": {
            "requested_topic": requested_topic,
            "requested_knowledge_points": [
                str(item or "").strip()
                for item in (sp.get("knowledge_points") or spec_data.get("knowledge_points") or [])
                if str(item or "").strip()
            ],
            "requested_practice_goal": requested_config["practice_goal"],
            "requested_intuition_kinds": requested_config["intuition_kinds"],
        },
        "question": {
            "stem": str((draft or {}).get("stem") or "").strip(),
            "answer": str((draft or {}).get("answer") or "").strip(),
            "analysis": str((draft or {}).get("analysis") or "").strip(),
            "intuition_packet": (draft or {}).get("intuition_packet")
            if isinstance((draft or {}).get("intuition_packet"), dict)
            else {},
        },
        "issues": list(issues or []) if isinstance(issues, list) else [],
        "output_schema": {
            "stem": "string",
            "answer": "string",
            "analysis": "string",
            "intuition_packet": "object (same version 1.0 packet contract, repaired consistently)",
        },
    }
    selected_goal_repair = ""
    if requested_config["practice_goal"] == "solution_appreciation":
        selected_goal_repair = (
            "<selected_goal_repair>The replacement stem itself must ask the learner to find or construct two genuinely "
            "different routes/representations and compare them under explicit structural criteria, without naming the "
            "routes or preferred winner in advance. The underlying scored object must remain non-mechanical after the "
            "comparison sentence is removed. Rebuild the whole mother task if necessary; never leave appreciation only "
            "inside intuition_packet.</selected_goal_repair>\n"
        )

    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    _prompt("question.repair.minimal.v1")
                    + "\n\n"
                    "<role>You are a curriculum question-repair assistant responsible for repairing a question according to the reported hard-gate issues.</role>\n"
                    "<edit_principle>Prefer changing only problematic parts while preserving curriculum scope, knowledge point, question type, and practice-stage order. Do not preserve a wrong intuition atom or a mechanically shallow mother task.</edit_principle>\n"
                    "<packet_integrity>Repair stem, answer, analysis, and intuition_packet together. The required perception/model_externalization/transfer stages must remain mutually consistent.</packet_integrity>\n"
                    "<alignment_repair>For intuition_mismatch, first identify the stem's actual decisive structure, then make the atom, formal anchor, every stage prompt/expected answer, answer, and analysis train that same structure. If the intended atom is better, rebuild the stem around it.</alignment_repair>\n"
                    "<depth_repair>For structural_depth_insufficient, rebuild the mother task rather than merely polishing wording: remove any fully specified solution recipe and require the learner to discover or select a relation, invariant, representation, boundary, counterexample, causal model, or evidence pattern. Transfer must change more than numbers. solution_appreciation must compare genuinely different solution paths, not cosmetic rewrites.</depth_repair>\n"
                    "<request_contract_repair>For request_contract_mismatch, rebuild the scored mother task so every requested topic and knowledge clause is necessary, preserve the exact requested practice_goal and intuition_kinds, and ground the repair in the supplied request_contract. Never satisfy the request only in hints, feedback, or commentary.</request_contract_repair>\n"
                    + selected_goal_repair
                    + "<no_cosmetic_repair>Do not fix a depth or alignment failure by adding reflective prose after an unchanged mechanical exercise.</no_cosmetic_repair>\n"
                    "<latex_rules>Inline formulas: \\(...\\). Display formulas: \\[...\\]. Do not use $...$.</latex_rules>\n"
                    "<verification>After modification, verify answer correctness and ensure stem/answer/analysis are fully self-consistent.</verification>\n"
                    "<output_format>Output a strict JSON object only.</output_format>"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.25,
        max_tokens=0,
        req_id_prefix="ql_repair",
        retries=2,
        raise_on_fail=False,
        stage_id="judge",
        stage_label="快速校验",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    out = dict(draft or {})
    out["stem"] = str(obj.get("stem") or out.get("stem") or "").strip()
    out["answer"] = str(obj.get("answer") or out.get("answer") or "").strip()
    out["analysis"] = str(obj.get("analysis") or out.get("analysis") or "").strip()
    out["intuition_packet"] = normalize_intuition_packet(
        obj.get("intuition_packet") if isinstance(obj.get("intuition_packet"), dict) else existing_packet,
        practice_config=requested_config,
        atom=existing_packet.get("atom") if isinstance(existing_packet.get("atom"), dict) else {},
        subject=str(sp.get("subject") or spec_data.get("subject") or "").strip(),
        topic=requested_topic,
        legacy_question=out,
    )
    return out


def _judge_payload_preview(draft: dict) -> dict:
    if not isinstance(draft, dict):
        return {}
    return {
        "stem": _clip(str(draft.get("stem") or "").strip(), 320),
        "answer": _clip(str(draft.get("answer") or "").strip(), 180),
        "analysis": _clip(str(draft.get("analysis") or "").strip(), 240),
    }


def _normalize_judge_output(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    out = dict(value)
    out["issues"] = list(out.get("issues") or []) if isinstance(out.get("issues"), list) else []
    return out
