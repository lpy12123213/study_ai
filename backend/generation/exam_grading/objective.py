from __future__ import annotations

import re
from typing import Any, Dict


def _normalize_question_type(question_type: str) -> str:
    raw = str(question_type or "").strip().lower()
    if any(key in raw for key in ("multi", "多选")):
        return "multi_choice"
    if any(key in raw for key in ("single", "choice", "选择", "单选")):
        return "single_choice"
    if any(key in raw for key in ("fill", "blank", "填空")):
        return "fill_blank"
    return raw


def is_objective_question(question_type: str) -> bool:
    return _normalize_question_type(question_type) in {"single_choice", "multi_choice", "fill_blank"}


def _option_tokens(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            out.extend(_option_tokens(item))
        return out
    raw = str(value or "").strip().upper()
    if not raw:
        return []
    tokens = [x for x in re.split(r"[\s,，;；、|/]+", raw) if x]
    if len(tokens) == 1 and re.fullmatch(r"[A-Z]+", tokens[0]) and len(tokens[0]) > 1:
        tokens = list(tokens[0])
    return [x.strip().upper() for x in tokens if x.strip()]


def _fill_slots(value: Any) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    tokens = [x for x in re.split(r"[;；|、]+", raw) if x]
    return [x for x in tokens if str(x or "").strip()]


def _fill_alternatives(value: Any) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    tokens = [x for x in re.split(r"(?:\s+或\s+)|(?:\s+or\s+)", raw, flags=re.IGNORECASE) if x]
    return [_normalize_fill(x) for x in tokens if _normalize_fill(x)]


def _fill_tokens(value: Any) -> list[str]:
    out: list[str] = []
    for slot in _fill_slots(value):
        out.extend(_fill_alternatives(slot))
    return out


def _normalize_fill(value: Any) -> str:
    raw = str(value or "").strip().lower()
    raw = re.sub(r"\s+", "", raw)
    raw = raw.replace("（", "(").replace("）", ")")
    return raw


def _score(is_correct: bool, max_score: float) -> float:
    return float(max_score or 0.0) if is_correct else 0.0


def grade_objective_answer(
    *,
    question_type: str,
    expected_answer: str,
    answer_data: Dict[str, Any],
    max_score: float,
) -> Dict[str, Any]:
    """Grade deterministic objective question types."""

    qtype = _normalize_question_type(question_type)
    expected = str(expected_answer or "").strip()
    if qtype in {"single_choice", "multi_choice"}:
        selected = answer_data.get("selected_options")
        if selected is None:
            selected = answer_data.get("selectedOptions")
        expected_set = set(_option_tokens(expected))
        selected_set = set(_option_tokens(selected))
        is_correct = bool(expected_set) and expected_set == selected_set
        return {
            "is_correct": is_correct,
            "score": _score(is_correct, max_score),
            "max_score": float(max_score or 0.0),
            "grading_json": {
                "mode": qtype,
                "expected": sorted(expected_set),
                "selected": sorted(selected_set),
            },
        }

    if qtype == "fill_blank":
        submitted = answer_data.get("fill_blank_text")
        if submitted is None:
            submitted = answer_data.get("fillBlankText")
        expected_slots = _fill_slots(expected)
        submitted_slots = _fill_slots(submitted)
        if len(expected_slots) > 1 or len(submitted_slots) > 1:
            is_correct = bool(expected_slots) and len(expected_slots) == len(submitted_slots)
            if is_correct:
                for expected_slot, submitted_slot in zip(expected_slots, submitted_slots):
                    accepted_slot = set(_fill_alternatives(expected_slot))
                    if _normalize_fill(submitted_slot) not in accepted_slot:
                        is_correct = False
                        break
            expected_detail = [sorted(set(_fill_alternatives(slot))) for slot in expected_slots]
            submitted_detail: Any = [_normalize_fill(slot) for slot in submitted_slots]
        else:
            accepted = set(_fill_tokens(expected))
            normalized = _normalize_fill(submitted)
            is_correct = bool(accepted) and normalized in accepted
            expected_detail = sorted(accepted)
            submitted_detail = normalized
        return {
            "is_correct": is_correct,
            "score": _score(is_correct, max_score),
            "max_score": float(max_score or 0.0),
            "grading_json": {
                "mode": qtype,
                "expected": expected_detail,
                "submitted": submitted_detail,
            },
        }

    return {
        "is_correct": None,
        "score": 0.0,
        "max_score": float(max_score or 0.0),
        "grading_json": {"mode": "unsupported_objective_type"},
    }
