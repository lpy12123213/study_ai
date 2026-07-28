from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List, Optional

PRACTICE_GOALS = {
    "fluency",
    "structural_intuition",
    "intuition_correction",
    "transfer",
    "solution_appreciation",
}
INTUITION_KINDS = {
    "prediction",
    "representation",
    "invariant",
    "boundary",
    "counterexample",
    "solution_comparison",
}
FEEDBACK_MODES = {"guided", "concise", "reflective"}
PACKET_STAGES = {
    "perception",
    "model_externalization",
    "minimal_check",
    "transfer",
    "appreciation",
}

DEFAULT_INTUITION_PRACTICE: Dict[str, Any] = {
    "practice_goal": "structural_intuition",
    "intuition_kinds": ["prediction", "representation", "invariant"],
    "packet_size": 3,
    "feedback_mode": "guided",
}


def _text(value: Any, *, limit: int = 600) -> str:
    text = str(value or "").strip()
    if limit > 0 and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def normalize_intuition_practice_config(value: Any) -> dict:
    raw = value if isinstance(value, dict) else {}
    goal = _text(raw.get("practice_goal"), limit=40)
    if goal not in PRACTICE_GOALS:
        goal = str(DEFAULT_INTUITION_PRACTICE["practice_goal"])

    kinds: List[str] = []
    raw_kinds = raw.get("intuition_kinds") if isinstance(raw.get("intuition_kinds"), list) else []
    for item in raw_kinds:
        kind = _text(item, limit=40)
        if kind in INTUITION_KINDS and kind not in kinds:
            kinds.append(kind)
    if not kinds:
        kinds = list(DEFAULT_INTUITION_PRACTICE["intuition_kinds"])

    try:
        packet_size = int(raw.get("packet_size") or DEFAULT_INTUITION_PRACTICE["packet_size"])
    except (TypeError, ValueError):
        packet_size = int(DEFAULT_INTUITION_PRACTICE["packet_size"])
    packet_size = max(3, min(packet_size, 5))
    if goal == "solution_appreciation":
        packet_size = max(4, packet_size)

    feedback_mode = _text(raw.get("feedback_mode"), limit=40)
    if feedback_mode not in FEEDBACK_MODES:
        feedback_mode = str(DEFAULT_INTUITION_PRACTICE["feedback_mode"])

    return {
        "practice_goal": goal,
        "intuition_kinds": kinds,
        "packet_size": packet_size,
        "feedback_mode": feedback_mode,
    }


def fallback_intuition_atom(*, subject: str = "", topic: str = "", seed_tag: str = "") -> dict:
    subject_text = _text(subject, limit=80) or "本学科"
    topic_text = _text(topic, limit=120) or "当前知识点"
    cue = _text(seed_tag, limit=100) or "决定结论的结构线索"
    return {
        "concept": topic_text,
        "internal_model": f"把{topic_text}看成可以比较、变化并检验的对象，而不是只记结论。",
        "mental_action": "先预测，再换表征或抓住不变量，最后用最短证据校准。",
        "decisive_cue": cue,
        "expected_first_feel": f"先形成关于{topic_text}的方向性判断，不急于展开完整运算。",
        "common_false_intuition": f"只凭熟悉题型或表面数字作答，忽略{subject_text}对象真正变化的结构。",
        "formal_anchor": "用一个最短的逻辑、计算、图示、反例或文本证据验证第一感觉。",
        "transfer_mutation": "保留决定性结构，同时改变数字、表征、设问方向或情境中的至少两项。",
        "boundary_flip": "改变一个关键条件，观察原判断何时不再成立。",
        "feedback": "指出第一感觉抓住了什么、偏差来自哪里，再用同结构异表面的任务复练。",
    }


def normalize_intuition_atom(
    value: Any,
    *,
    subject: str = "",
    topic: str = "",
    seed_tag: str = "",
) -> dict:
    raw = value if isinstance(value, dict) else {}
    fallback = fallback_intuition_atom(subject=subject, topic=topic, seed_tag=seed_tag)
    aliases = {
        "concept": ("concept", "knowledge_object"),
        "internal_model": ("internal_model", "mental_model"),
        "mental_action": ("mental_action", "operation"),
        "decisive_cue": ("decisive_cue", "key_cue"),
        "expected_first_feel": ("expected_first_feel", "first_feel", "prediction"),
        "common_false_intuition": ("common_false_intuition", "false_intuition", "misconception"),
        "formal_anchor": ("formal_anchor", "verification"),
        "transfer_mutation": ("transfer_mutation", "transfer"),
        "boundary_flip": ("boundary_flip", "boundary"),
        "feedback": ("feedback", "feedback_strategy"),
    }
    out: Dict[str, str] = {}
    for key, candidates in aliases.items():
        selected = ""
        for candidate in candidates:
            selected = _text(raw.get(candidate), limit=600)
            if selected:
                break
        out[key] = selected or str(fallback[key])
    return out


def _stage_alias(value: Any) -> str:
    raw = _text(value, limit=50).lower()
    aliases = {
        "predict": "perception",
        "prediction": "perception",
        "explain": "model_externalization",
        "explanation": "model_externalization",
        "verify": "minimal_check",
        "verification": "minimal_check",
        "boundary": "appreciation",
        "compare": "appreciation",
        "comparison": "appreciation",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in PACKET_STAGES else ""


def _kind_alias(value: Any, *, stage: str) -> str:
    raw = _text(value, limit=50).lower()
    aliases = {
        "predict": "prediction",
        "explain": "representation",
        "compare": "solution_comparison",
        "comparison": "solution_comparison",
    }
    normalized = aliases.get(raw, raw)
    if normalized in INTUITION_KINDS:
        return normalized
    defaults = {
        "perception": "prediction",
        "model_externalization": "representation",
        "minimal_check": "invariant",
        "transfer": "representation",
        "appreciation": "solution_comparison",
    }
    return defaults.get(stage, "prediction")


def normalize_intuition_stage(value: Any) -> Optional[dict]:
    if not isinstance(value, dict):
        return None
    stage = _stage_alias(value.get("stage") or value.get("phase") or value.get("name"))
    prompt = _text(value.get("prompt") or value.get("question") or value.get("task"), limit=1600)
    if not stage or not prompt:
        return None
    out = {
        "stage": stage,
        "kind": _kind_alias(value.get("kind") or value.get("intuition_kind"), stage=stage),
        "prompt": prompt,
    }
    for key, aliases in {
        "hint": ("hint", "scaffold"),
        "expected_answer": ("expected_answer", "answer", "reference_answer"),
        "feedback": ("feedback", "feedback_text"),
    }.items():
        selected = ""
        for alias in aliases:
            selected = _text(value.get(alias), limit=1600)
            if selected:
                break
        if selected:
            out[key] = selected
    return out


def _fallback_stages(question: dict, atom: dict) -> List[dict]:
    stem = _text(question.get("stem"), limit=1600)
    answer = _text(question.get("answer"), limit=1600)
    analysis = _text(question.get("analysis"), limit=2000)
    return [
        {
            "stage": "perception",
            "kind": "prediction",
            "prompt": stem or "暂不展开完整计算，先写下你的第一判断和把握程度。",
            "hint": _text(atom.get("decisive_cue"), limit=500),
            "expected_answer": answer,
            "feedback": _text(atom.get("feedback"), limit=800),
        },
        {
            "stage": "model_externalization",
            "kind": "representation",
            "prompt": "说明你脑中看见的对象、变化关系和决定性线索，并用最短证据检验第一判断。",
            "hint": _text(atom.get("formal_anchor"), limit=500),
            "expected_answer": analysis or answer,
            "feedback": _text(atom.get("feedback"), limit=800),
        },
        {
            "stage": "transfer",
            "kind": "representation",
            "prompt": _text(atom.get("transfer_mutation"), limit=1000),
            "hint": "保留决定性结构，不要只替换一个数字。",
            "expected_answer": "迁移后的结论应依据同一决定性结构重新判断，并用简短证据验证。",
            "feedback": _text(atom.get("feedback"), limit=800),
        },
    ]


def normalize_intuition_packet(
    value: Any,
    *,
    practice_config: Any = None,
    atom: Any = None,
    subject: str = "",
    topic: str = "",
    seed_tag: str = "",
    legacy_question: Optional[dict] = None,
) -> dict:
    raw = value if isinstance(value, dict) else {}
    config_input = dict(practice_config) if isinstance(practice_config, dict) else dict(raw)
    raw_stages_for_config = raw.get("stages") if isinstance(raw.get("stages"), list) else []
    if "packet_size" not in config_input and raw_stages_for_config:
        config_input["packet_size"] = len(raw_stages_for_config)
    if "intuition_kinds" not in config_input and raw_stages_for_config:
        config_input["intuition_kinds"] = [
            str((item or {}).get("kind") or "").strip()
            for item in raw_stages_for_config
            if isinstance(item, dict) and str((item or {}).get("kind") or "").strip()
        ]
    config = normalize_intuition_practice_config(config_input)
    normalized_atom = normalize_intuition_atom(
        raw.get("atom") if isinstance(raw.get("atom"), dict) else atom,
        subject=subject,
        topic=topic,
        seed_tag=seed_tag,
    )

    stages: List[dict] = []
    seen_stage_names: set[str] = set()
    for item in raw.get("stages") if isinstance(raw.get("stages"), list) else []:
        normalized = normalize_intuition_stage(item)
        if not normalized:
            continue
        key = str(normalized["stage"])
        if key in seen_stage_names:
            continue
        seen_stage_names.add(key)
        stages.append(normalized)

    # Accept the early keyed packet shape as input, then persist one canonical list shape.
    for key in ("predict", "explain", "verify", "transfer", "boundary", "compare"):
        item = raw.get(key)
        if not isinstance(item, dict):
            continue
        normalized = normalize_intuition_stage({**item, "stage": key})
        if not normalized:
            continue
        signature = str(normalized["stage"])
        if signature not in seen_stage_names:
            stages.append(normalized)
            seen_stage_names.add(signature)

    if not stages:
        stages = _fallback_stages(legacy_question or {}, normalized_atom)

    stage_by_name = {str(item.get("stage") or ""): item for item in stages if isinstance(item, dict)}
    selected_names = {name for name in ("perception", "model_externalization", "transfer") if name in stage_by_name}
    extra_slots = max(0, int(config["packet_size"]) - len(selected_names))
    optional_priority = (
        ("appreciation", "minimal_check")
        if config["practice_goal"] == "solution_appreciation"
        else ("minimal_check", "appreciation")
    )
    for name in optional_priority:
        if extra_slots <= 0:
            break
        if name in stage_by_name and name not in selected_names:
            selected_names.add(name)
            extra_slots -= 1
    canonical_order = ("perception", "model_externalization", "minimal_check", "transfer", "appreciation")
    stages = [stage_by_name[name] for name in canonical_order if name in selected_names]

    alignment_raw = raw.get("curriculum_alignment") if isinstance(raw.get("curriculum_alignment"), dict) else {}
    knowledge_points = [
        _text(item, limit=120)
        for item in (alignment_raw.get("knowledge_points") or [])
        if _text(item, limit=120)
    ][:12]
    curriculum_alignment: Dict[str, Any] = {
        "knowledge_points": knowledge_points,
        "scope_note": _text(alignment_raw.get("scope_note"), limit=800),
    }
    if "in_scope" in alignment_raw:
        curriculum_alignment["in_scope"] = bool(alignment_raw.get("in_scope"))

    validation_raw = raw.get("validation") if isinstance(raw.get("validation"), dict) else {}
    validation: Dict[str, Any] = {
        "status": _text(validation_raw.get("status"), limit=20) or "pending",
        "scope_ok": bool(validation_raw.get("scope_ok", False)),
        "answer_correct": bool(validation_raw.get("answer_correct", False)),
        "answer_analysis_consistent": bool(validation_raw.get("answer_analysis_consistent", False)),
        "conditions_sufficient": bool(validation_raw.get("conditions_sufficient", False)),
        "unambiguous": bool(validation_raw.get("unambiguous", False)),
        "transfer_valid": bool(validation_raw.get("transfer_valid", False)),
        "intuition_aligned": bool(validation_raw.get("intuition_aligned", False)),
        "structural_depth": bool(validation_raw.get("structural_depth", False)),
        "request_aligned": bool(validation_raw.get("request_aligned", False)),
        "issues": [
            _text(item, limit=300)
            for item in (validation_raw.get("issues") or [])
            if _text(item, limit=300)
        ][:12],
        "repaired": bool(validation_raw.get("repaired", False)),
    }
    if validation["status"] not in {"pending", "passed", "failed"}:
        validation["status"] = "pending"

    return {
        "version": "1.0",
        "practice_goal": config["practice_goal"],
        "atom": normalized_atom,
        "stages": stages,
        "curriculum_alignment": curriculum_alignment,
        "validation": validation,
    }


def validate_intuition_packet_structure(packet: Any, *, packet_size: int = 3) -> List[str]:
    if not isinstance(packet, dict):
        return ["intuition_packet_missing"]
    atom = packet.get("atom") if isinstance(packet.get("atom"), dict) else {}
    issues: List[str] = []
    for key in ("concept", "internal_model", "decisive_cue", "formal_anchor", "transfer_mutation"):
        if not _text(atom.get(key), limit=10_000):
            issues.append(f"intuition_atom_missing:{key}")

    stages = packet.get("stages") if isinstance(packet.get("stages"), list) else []
    stage_names = {str((item or {}).get("stage") or "") for item in stages if isinstance(item, dict)}
    for required in ("perception", "model_externalization", "transfer"):
        if required not in stage_names:
            issues.append(f"intuition_stage_missing:{required}")
    if str(packet.get("practice_goal") or "") == "solution_appreciation" and "appreciation" not in stage_names:
        issues.append("intuition_stage_missing:appreciation")
    expected_size = max(3, min(int(packet_size or 3), 5))
    if len(stages) < expected_size:
        issues.append("intuition_packet_too_short")
    for item in stages:
        if not isinstance(item, dict) or not _text(item.get("prompt"), limit=10_000):
            issues.append("intuition_stage_prompt_missing")
            break
    return list(dict.fromkeys(issues))


def attach_quick_validation(packet: dict, report: dict, *, repaired: bool) -> dict:
    out = copy.deepcopy(packet if isinstance(packet, dict) else {})
    passed = bool((report or {}).get("pass"))
    validation = {
        "status": "passed" if passed else "failed",
        "scope_ok": bool((report or {}).get("scope_ok")),
        "answer_correct": bool((report or {}).get("answer_correct")),
        "answer_analysis_consistent": bool((report or {}).get("answer_analysis_consistent")),
        "conditions_sufficient": bool((report or {}).get("conditions_sufficient")),
        "unambiguous": bool((report or {}).get("unambiguous")),
        "transfer_valid": bool((report or {}).get("transfer_valid")),
        "intuition_aligned": bool((report or {}).get("intuition_aligned")),
        "structural_depth": bool((report or {}).get("structural_depth")),
        "request_aligned": bool((report or {}).get("request_aligned")),
        "issues": [
            _text(item, limit=300)
            for item in ((report or {}).get("issues") or [])
            if _text(item, limit=300)
        ][:12],
        "repaired": bool(repaired),
    }
    out["validation"] = validation
    alignment = out.get("curriculum_alignment") if isinstance(out.get("curriculum_alignment"), dict) else {}
    out["curriculum_alignment"] = {**alignment, "in_scope": validation["scope_ok"]}
    return out


def intuition_packet_signature(packet: Any) -> str:
    if not isinstance(packet, dict):
        return ""
    atom = packet.get("atom") if isinstance(packet.get("atom"), dict) else {}
    stages = packet.get("stages") if isinstance(packet.get("stages"), list) else []
    parts = [
        _text(atom.get("concept"), limit=300),
        _text(atom.get("decisive_cue"), limit=500),
        *[_text((item or {}).get("prompt"), limit=1200) for item in stages if isinstance(item, dict)],
    ]
    text = " ".join(part for part in parts if part).lower()
    text = re.sub(r"\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]", " <formula> ", text)
    text = re.sub(r"\d+(?:\.\d+)?", "<number>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:5000]


def intuition_packet_json(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return ""
