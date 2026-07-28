from __future__ import annotations

import hashlib
import re

from backend.generation.question_library.gen_common import DEFAULT_SEARCH_CONFIG
from backend.generation.question_library.gen_utils import _difficulty_gap_ratio
from backend.generation.question_library.intuition_practice import normalize_intuition_atom

_GENERIC_ATOM_MARKERS = (
    "决定结论的结构线索",
    "先预测，再换表征或抓住不变量",
    "用一个最短的逻辑、计算、图示、反例或文本证据",
    "保留决定性结构，同时改变数字",
    "只凭熟悉题型或表面数字作答",
)

_ROUTINE_TEMPLATE_MARKERS = (
    "套公式",
    "代入即可",
    "直接代入",
    "公式代入",
    "照公式计算",
    "使用公式法",
    "直接求导",
    "求单调区间",
    "只需计算",
    "机械计算",
    "按下列步骤",
    "指定完整方法",
    "完整方法已给出",
    "direct substitution",
    "substitute into the formula",
    "follow the supplied steps",
)

_METHOD_LEAK_MARKERS = (
    "分别使用",
    "先用公式",
    "再用公式",
    "题面给出决定性线索",
    "题面明示",
    "直接告诉",
    "use method a and method b",
    "state the decisive cue",
)

_ROUTINE_SCAFFOLD_MARKERS = (
    "先求通项",
    "先求参数",
    "先求公差",
    "第一问求通项",
    "第一问求参数",
    "再代入公式",
    "再求前n项和",
    "再求最值",
    "find the general term first",
    "find the parameters first",
    "then substitute",
)

_GIVEN_FORMULA_MARKERS = (
    "已知通项",
    "给定通项",
    "给出通项",
    "a_n=",
    "a_{n}=",
    "given the general term",
)

_EXTREMUM_TASK_MARKERS = (
    "求sn最大",
    "求s_n最大",
    "求前n项和的最大",
    "求部分和最大",
    "find the maximum of s",
    "find the extremum of s",
)

_METHOD_COMPARISON_MARKERS = (
    "比较两种方法",
    "比较两种解法",
    "对比两种方法",
    "二次函数法和符号法",
    "compare two methods",
    "compare the methods",
)

_TOPIC_FOCUS_GROUPS = (
    ("symmetry", ("对称", "镜像", "配对", "symmetry", "symmetric")),
    ("invariant", ("不变量", "保持不变", "恒定结构", "守恒", "invariant", "conservation")),
    ("representation", ("表征", "数形", "图像", "几何视角", "representation")),
    ("boundary", ("边界", "临界", "极端", "boundary", "limiting case")),
    ("counterexample", ("反例", "counterexample")),
)

_NUMBER_ONLY_TRANSFER_MARKERS = (
    "只改数字",
    "仅改数字",
    "只换数字",
    "仅换数字",
    "替换数字即可",
    "number-only",
    "change only the numbers",
)

_STRUCTURAL_SIGNAL_GROUPS = (
    (
        "表征",
        "图像",
        "几何",
        "代数",
        "坐标",
        "模型",
        "数形",
        "representation",
        "geometric",
        "algebraic",
    ),
    (
        "不变量",
        "对称",
        "守恒",
        "配对",
        "对应",
        "周期",
        "invariant",
        "symmetry",
        "conservation",
    ),
    (
        "边界",
        "极端",
        "临界",
        "反例",
        "翻转",
        "失效",
        "必要条件",
        "充分条件",
        "boundary",
        "counterexample",
        "extreme case",
    ),
    (
        "关系",
        "约束",
        "条件反推",
        "逆向",
        "构造",
        "参数变化",
        "分类讨论",
        "infer",
        "relationship",
        "constraint",
        "construct",
    ),
)


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    blob = str(text or "").lower()
    return any(marker.lower() in blob for marker in markers)


def _template_risk(text: str) -> float:
    """Estimate routine/method-leak risk without hard-rejecting compact ideas."""

    risk = 0.08
    if _has_any(text, _ROUTINE_TEMPLATE_MARKERS):
        risk += 0.38
    if _has_any(text, _METHOD_LEAK_MARKERS):
        risk += 0.24
    if _has_any(text, _NUMBER_ONLY_TRANSFER_MARKERS):
        risk += 0.3
    scaffold_hits = sum(1 for marker in _ROUTINE_SCAFFOLD_MARKERS if marker.lower() in text.lower())
    if scaffold_hits >= 2:
        risk += 0.34
    elif scaffold_hits == 1:
        risk += 0.12
    if "第一步" in text and "第二步" in text:
        risk += 0.18
    given_formula_extremum = _has_any(text, _GIVEN_FORMULA_MARKERS) and _has_any(text, _EXTREMUM_TASK_MARKERS)
    if given_formula_extremum:
        risk += 0.42
    if given_formula_extremum and _has_any(text, _METHOD_COMPARISON_MARKERS):
        risk += 0.28
    return min(1.0, risk)


def _topic_binding_score(topic: str, design_text: str) -> tuple[float, tuple[str, ...]]:
    """Score explicit structural topic clauses against the actual seed design."""

    # The title/head names the requested disciplinary structures. Text after a
    # colon or a new line commonly contains authoring instructions with choices
    # such as "change the relation, boundary, or representation"; treating those
    # alternatives as simultaneous mother-task requirements would wrongly cap
    # otherwise well-bound candidates before realization.
    topic_blob = re.split(r"[:：\r\n]", str(topic or ""), maxsplit=1)[0].lower()
    design_blob = str(design_text or "").lower()
    required: list[tuple[str, tuple[str, ...]]] = []
    for label, aliases in _TOPIC_FOCUS_GROUPS:
        if any(alias.lower() in topic_blob for alias in aliases):
            required.append((label, aliases))
    if not required:
        return 1.0, ()
    matched = sum(1 for _label, aliases in required if any(alias.lower() in design_blob for alias in aliases))
    missing = tuple(label for label, aliases in required if not any(alias.lower() in design_blob for alias in aliases))
    return matched / len(required), missing


def _structural_depth_signal(text: str, *, genericity: float, template_risk: float) -> float:
    """Reward distinct structural actions, not verbosity or derivation length."""

    group_hits = sum(1 for group in _STRUCTURAL_SIGNAL_GROUPS if _has_any(text, group))
    depth = 0.12 + 0.2 * group_hits
    if _has_any(text, ("隐藏", "非显式", "发现", "推断", "重构", "hidden", "discover")):
        depth += 0.1
    depth -= 0.24 * genericity
    depth -= 0.32 * template_risk
    return max(0.0, min(1.0, depth))


def _specific_cue_score(text: str) -> float:
    cue = str(text or "").strip()
    if not cue:
        return 0.0
    if _has_any(cue, _GENERIC_ATOM_MARKERS):
        return 0.15
    structural_hits = sum(1 for group in _STRUCTURAL_SIGNAL_GROUPS if _has_any(cue, group))
    return min(1.0, 0.45 + 0.18 * structural_hits)


def _transfer_quality(text: str) -> float:
    transfer = str(text or "").strip()
    if not transfer:
        return 0.0
    if _has_any(transfer, _NUMBER_ONLY_TRANSFER_MARKERS):
        return 0.05
    structural_mutation = _has_any(
        transfer,
        (
            "关系",
            "约束",
            "边界",
            "条件方向",
            "表征",
            "反例",
            "relation",
            "constraint",
            "boundary",
            "representation",
        ),
    )
    return 0.9 if structural_mutation else 0.4


def _stable_jitter(key: str, *, magnitude: float) -> float:
    """Deterministic jitter for tie-breaking.

    The question library spec search should be reproducible: selection and scoring
    should not depend on process-global RNG state (which makes tests flaky and
    makes production behavior hard to debug).
    """

    mag = float(magnitude or 0.0)
    if mag <= 0.0:
        return 0.0
    mag = min(mag, 0.02)  # Keep jitter small: it should not dominate signal.

    raw = str(key or "")
    h = hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()
    v = int(h[:8], 16)  # 32-bit
    u = v / 0xFFFFFFFF  # 0..1
    return (u * 2.0 - 1.0) * mag  # -mag..+mag


def score_spec(spec: dict, source_pack: dict, config: dict) -> dict:
    out = dict(spec or {})
    sp = source_pack or {}
    spec_id = str(out.get("spec_id") or "").strip()
    difficulty = str(out.get("difficulty") or "").strip()
    target_difficulty = str((config or {}).get("target_difficulty") or difficulty).strip()
    skill = str(out.get("skill") or "").strip()
    reasoning = str(out.get("reasoning") or "").strip()
    trap = str(out.get("trap") or "").strip()
    surface = str(out.get("surface") or "").strip()
    seed_tag = str(out.get("seed_tag") or "").strip()

    # Normalize sub-scores to [0, 1].  The search now rewards a usable intuition
    # atom instead of treating long derivations and keyword density as proxies for
    # mathematical thinking.
    difficulty_match = max(0.0, 1.0 - _difficulty_gap_ratio(target_difficulty, difficulty))
    raw_atom = out.get("intuition_atom") if isinstance(out.get("intuition_atom"), dict) else {}
    atom = normalize_intuition_atom(
        raw_atom,
        subject=str(out.get("subject") or ""),
        topic=str(out.get("topic") or ""),
        seed_tag=seed_tag,
    )
    out["intuition_atom"] = atom

    atom_fields = (
        "concept",
        "internal_model",
        "mental_action",
        "decisive_cue",
        "expected_first_feel",
        "common_false_intuition",
        "formal_anchor",
        "transfer_mutation",
    )
    completeness = sum(1 for key in atom_fields if str(raw_atom.get(key) or "").strip()) / len(atom_fields)
    atom_blob = " ".join(str(atom.get(key) or "").strip() for key in atom_fields)
    authored_topic_parts = [
        str(out.get("brainstorm_concept") or ""),
        str(out.get("brainstorm_angle") or ""),
        str(out.get("brainstorm_novelty_note") or ""),
        str(out.get("brainstorm_mother_question_demand") or ""),
        str(out.get("brainstorm_topic_binding") or ""),
        " ".join(str(raw_atom.get(key) or "").strip() for key in atom_fields),
        str(raw_atom.get("boundary_flip") or ""),
    ]
    topic_evidence_blob = " ".join(authored_topic_parts)
    design_blob = " ".join(
        [skill, reasoning, trap, surface, topic_evidence_blob, atom_blob, str(atom.get("boundary_flip") or "")]
    )
    generic_hits = sum(1 for marker in _GENERIC_ATOM_MARKERS if marker in atom_blob)
    genericity = min(1.0, generic_hits / 3.0)
    template_similarity = _template_risk(design_blob)
    # Topic binding must be evidenced by authored seed fields. The normalized
    # fallback atom echoes the requested topic and therefore cannot prove that a
    # candidate actually incorporates its clauses.
    topic_binding_score, missing_topic_focus = _topic_binding_score(
        str(out.get("topic") or ""), topic_evidence_blob
    )
    structural_depth_score = _structural_depth_signal(
        design_blob,
        genericity=genericity,
        template_risk=template_similarity,
    )
    cue_specificity = _specific_cue_score(str(atom.get("decisive_cue") or ""))
    transfer_specificity = _transfer_quality(str(atom.get("transfer_mutation") or ""))
    false_intuition = str(atom.get("common_false_intuition") or "").strip()
    correction_value = 0.2 if _has_any(false_intuition, _GENERIC_ATOM_MARKERS) else (0.8 if false_intuition else 0.0)
    internal_model = str(atom.get("internal_model") or "").strip()
    model_specificity = 0.2 if _has_any(internal_model, _GENERIC_ATOM_MARKERS) else (0.8 if internal_model else 0.0)
    intuition_alignment = max(
        0.0,
        min(
            1.0,
            0.1 * completeness
            + 0.18 * cue_specificity
            + 0.14 * model_specificity
            + 0.12 * correction_value
            + 0.28 * structural_depth_score
            + 0.18 * transfer_specificity
            - 0.18 * genericity,
        ),
    )

    # Variety remains useful, but it is secondary to whether the idea exposes and
    # calibrates an internal model.
    novelty = 0.35
    if str(atom.get("boundary_flip") or "").strip():
        novelty += 0.2
    if str(atom.get("mental_action") or "").strip():
        novelty += 0.15
    if any(token in str(atom.get("transfer_mutation") or "") for token in ("表征", "逆向", "情境", "图", "代数")):
        novelty += 0.15
    novelty = min(1.0, novelty)

    skill_coverage = min(1.0, 0.35 + (0.2 if skill else 0.0) + 0.4 * intuition_alignment)

    solvability = 0.8
    if any(k in trap for k in ["多解", "歧义", "陷阱过多"]):
        solvability -= 0.25
    solvability = max(0.2, min(1.0, solvability))

    ambiguity_risk = 0.25
    if any(k in trap for k in ["定义域", "边界", "符号"]):
        ambiguity_risk += 0.15
    ambiguity_risk = min(1.0, ambiguity_risk)

    reference_patterns = [str(item or "").strip() for item in (sp.get("reference_patterns") or []) if str(item or "").strip()]
    reference_examples = sp.get("reference_examples") if isinstance(sp.get("reference_examples"), list) else []
    has_reference = bool(reference_patterns or reference_examples)
    reference_blob = " ".join(
        reference_patterns
        + [str((item or {}).get("why_selected") or "").strip() for item in reference_examples if isinstance(item, dict)]
        + [str((item or {}).get("stem") or "").strip() for item in reference_examples if isinstance(item, dict)]
    )
    reference_alignment = 0.5 if has_reference else 0.0
    matched_reference = False
    for token in [seed_tag, skill, reasoning, surface]:
        token_text = str(token or "").strip()
        if token_text and token_text in reference_blob:
            reference_alignment += 0.12
            matched_reference = True
    for kw in ["分类", "参数", "构造", "反例", "综合", "变化", "探究", "多步"]:
        if kw in reference_blob and kw in (f"{seed_tag} {skill} {reasoning} {surface}"):
            reference_alignment += 0.05
            matched_reference = True
    if has_reference and not matched_reference:
        reference_alignment = max(0.2, reference_alignment - 0.15)
    reference_alignment = min(1.0, reference_alignment)

    w_diff = float((config or {}).get("difficulty_match_weight") or 0.24)
    w_novel = float((config or {}).get("novelty_weight") or 0.14)
    w_skill = float((config or {}).get("skill_coverage_weight") or 0.14)
    w_solv = float((config or {}).get("solvability_weight") or 0.2)
    w_intuition = float((config or {}).get("intuition_alignment_weight") or 0.36)
    w_amb = float((config or {}).get("ambiguity_penalty") or 0.26)
    w_tpl = float((config or {}).get("template_penalty") or 0.16)
    w_ref = float((config or {}).get("reference_alignment_weight") or DEFAULT_SEARCH_CONFIG["reference_alignment_weight"])

    score = (
        w_diff * difficulty_match
        + w_novel * novelty
        + w_skill * skill_coverage
        + w_solv * solvability
        + w_intuition * intuition_alignment
        + w_ref * reference_alignment
        - w_amb * ambiguity_risk
        - w_tpl * template_similarity
    )

    # Explicit structural clauses in the requested topic are hard requirements.
    # A candidate that omits one receives a low ceiling even if generic novelty or
    # a bolted-on method comparison scores well elsewhere.
    if missing_topic_focus:
        score -= 0.4 * (1.0 - topic_binding_score)
        score = min(score, 0.18 + 0.32 * topic_binding_score)

    # Optional deterministic tie-breaker. Keep default as 0 to preserve ranking stability.
    jitter = float((config or {}).get("score_jitter") or 0.0)
    score += _stable_jitter(f"{spec_id}|{seed_tag}|{skill}|{reasoning}|{trap}|{surface}", magnitude=jitter)
    # Convert to a 0-100-ish scale for easier debugging.
    out["reference_alignment"] = round(reference_alignment, 4)
    out["intuition_alignment"] = round(intuition_alignment, 4)
    out["structural_depth_score"] = round(structural_depth_score, 4)
    out["template_similarity"] = round(template_similarity, 4)
    out["topic_binding_score"] = round(topic_binding_score, 4)
    out["missing_topic_focus"] = list(missing_topic_focus)
    out["score"] = float(max(0.0, min(1.0, score)) * 100.0)
    return out
