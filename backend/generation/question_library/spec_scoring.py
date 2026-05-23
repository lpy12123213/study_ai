from __future__ import annotations

import hashlib

from backend.generation.question_library.gen_common import DEFAULT_SEARCH_CONFIG
from backend.generation.question_library.gen_utils import _difficulty_gap_ratio


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

    # Normalize sub-scores to [0, 1].
    difficulty_match = max(0.0, 1.0 - _difficulty_gap_ratio(target_difficulty, difficulty))

    reasoning_depth = 0.25
    for kw in ["分类", "参数", "构造", "反证", "多步", "数形", "综合"]:
        if kw in reasoning:
            reasoning_depth += 0.12
    reasoning_depth = min(1.0, reasoning_depth)

    novelty = 0.25
    for kw in ["参数", "反例", "探究", "变化", "开放", "压轴", "综合"]:
        if kw in (surface + " " + reasoning + " " + skill):
            novelty += 0.1
    novelty = min(1.0, novelty)

    skill_coverage = 0.35 + (0.25 if skill else 0.0) + (0.25 if reasoning else 0.0)
    skill_coverage = min(1.0, skill_coverage)

    solvability = 0.8
    if any(k in trap for k in ["多解", "歧义", "陷阱过多"]):
        solvability -= 0.25
    solvability = max(0.2, min(1.0, solvability))

    ambiguity_risk = 0.25
    if any(k in trap for k in ["定义域", "边界", "符号"]):
        ambiguity_risk += 0.15
    ambiguity_risk = min(1.0, ambiguity_risk)

    template_similarity = 0.15
    for kw in ["求单调区间", "直接求导", "套公式", "代入即可"]:
        if kw in reasoning or kw in surface:
            template_similarity += 0.25
    template_similarity = min(1.0, template_similarity)

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
    w_novel = float((config or {}).get("novelty_weight") or 0.24)
    w_skill = float((config or {}).get("skill_coverage_weight") or 0.2)
    w_solv = float((config or {}).get("solvability_weight") or 0.2)
    w_amb = float((config or {}).get("ambiguity_penalty") or 0.26)
    w_tpl = float((config or {}).get("template_penalty") or 0.16)
    w_ref = float((config or {}).get("reference_alignment_weight") or DEFAULT_SEARCH_CONFIG["reference_alignment_weight"])

    score = (
        w_diff * difficulty_match
        + w_novel * novelty
        + w_skill * skill_coverage
        + w_solv * solvability
        + w_ref * reference_alignment
        - w_amb * ambiguity_risk
        - w_tpl * template_similarity
    )

    # Optional deterministic tie-breaker. Keep default as 0 to preserve ranking stability.
    jitter = float((config or {}).get("score_jitter") or 0.0)
    score += _stable_jitter(f"{spec_id}|{seed_tag}|{skill}|{reasoning}|{trap}|{surface}", magnitude=jitter)
    # Convert to a 0-100-ish scale for easier debugging.
    out["reference_alignment"] = round(reference_alignment, 4)
    out["score"] = float(max(0.0, min(1.0, score)) * 100.0 + reasoning_depth * 8.0)
    return out
