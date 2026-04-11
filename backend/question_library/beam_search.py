from __future__ import annotations

from typing import List

from backend.question_library.gen_common import (
    DEFAULT_SEARCH_CONFIG,
    _clip_unique,
    _difficulty_variants,
    get_reasoning_patterns,
    get_seed_tags,
    get_skills,
    get_surfaces,
    get_traps,
    _sample_unique,
)


def _expand_field(
    specs: List[dict],
    *,
    field: str,
    layer: str,
    options: List[str],
    branch_factor: int,
    budget: int,
) -> List[dict]:
    out: List[dict] = []
    max_children = max(1, int(branch_factor or 1))
    max_total = max(1, int(budget or 1))
    opts = _sample_unique(options, max_children)
    for spec in specs or []:
        if not isinstance(spec, dict):
            continue
        base = dict(spec)
        for opt in opts:
            child = dict(base)
            child[field] = opt
            child["layer"] = layer
            parent_id = str(base.get("spec_id") or "").strip() or "spec"
            child["spec_id"] = f"{parent_id}/{field}:{abs(hash(opt)) % 997}"
            out.append(child)
            if len(out) >= max_total:
                return out
    return out


def seed_root_specs(source_pack: dict, count: int, difficulty: str, question_type: str) -> List[dict]:
    subj = str((source_pack or {}).get("subject") or "").strip()
    top = str((source_pack or {}).get("topic") or "").strip()
    specs: List[dict] = []
    # Root seeding should create a small, diverse set of candidates (4-6) before expansion.
    target = max(1, min(int(count or 1), 10))
    n = max(4, min(6, max(4, target)))
    seed_tags = get_seed_tags(subj) or ["覆盖能力", "变化分析", "综合推理", "反例辨析", "条件反推", "应用迁移"]
    seed_tags = _clip_unique(seed_tags, n)
    difficulty_variants = _difficulty_variants(str(difficulty or "").strip(), len(seed_tags))
    for i, tag in enumerate(seed_tags):
        specs.append(
            {
                "spec_id": f"spec-{i + 1}",
                "subject": subj,
                "topic": top,
                "difficulty": difficulty_variants[i] if i < len(difficulty_variants) else str(difficulty or "").strip(),
                "question_type": str(question_type or "").strip(),
                "layer": "root",
                "seed_tag": tag,
            }
        )
    return specs


def seed_root_specs_from_brainstorm(
    source_pack: dict,
    seeds: List[dict],
    *,
    count: int,
    difficulty: str,
    question_type: str,
) -> List[dict]:
    """Convert brainstorm creative seeds into root specs.

    Expected seed fields (best-effort):
    - concept / angle / scenario / novelty_note
    - seed_tag / skill_hint / reasoning_hint
    """

    subj = str((source_pack or {}).get("subject") or "").strip()
    top = str((source_pack or {}).get("topic") or "").strip()
    target = max(1, min(int(count or 1), 10))
    n = max(4, min(10, max(4, target)))

    normalized: List[dict] = []
    for raw in seeds or []:
        if not isinstance(raw, dict):
            continue
        normalized.append(dict(raw))
        if len(normalized) >= n:
            break

    if not normalized:
        return seed_root_specs(source_pack, count=count, difficulty=difficulty, question_type=question_type)

    difficulty_variants = _difficulty_variants(str(difficulty or "").strip(), len(normalized))
    specs: List[dict] = []
    for i, seed in enumerate(normalized):
        concept = str(seed.get("concept") or "").strip()
        angle = str(seed.get("angle") or seed.get("reasoning_angle") or "").strip()
        scenario = str(seed.get("scenario") or "").strip()
        novelty = str(seed.get("novelty_note") or seed.get("novelty") or "").strip()
        seed_tag = str(seed.get("seed_tag") or seed.get("seedTag") or "").strip()
        if not seed_tag:
            seed_tag = concept or f"创意种子{i + 1}"

        spec: dict = {
            "spec_id": f"spec-{i + 1}",
            "subject": subj,
            "topic": top,
            "difficulty": difficulty_variants[i] if i < len(difficulty_variants) else str(difficulty or "").strip(),
            "question_type": str(question_type or "").strip(),
            "layer": "root",
            "seed_tag": seed_tag,
            # Carry brainstorm context downstream so draft_realization can leverage it.
            "brainstorm_concept": concept,
            "brainstorm_angle": angle,
            "brainstorm_scenario": scenario,
            "brainstorm_novelty_note": novelty,
            "brainstorm_skill_hint": str(seed.get("skill_hint") or "").strip(),
            "brainstorm_reasoning_hint": str(seed.get("reasoning_hint") or "").strip(),
        }
        specs.append(spec)
    return specs


def expand_skill_layer(specs: List[dict], config: dict) -> List[dict]:
    if not specs:
        return []
    subj = str((specs[0] or {}).get("subject") or "").strip()
    options = get_skills(subj) or ["概念辨析", "性质判定", "计算推导", "条件反推", "综合应用"]
    return _expand_field(
        specs,
        field="skill",
        layer="skill",
        options=options,
        branch_factor=int((config or {}).get("skill_branch_factor") or DEFAULT_SEARCH_CONFIG["skill_branch_factor"]),
        budget=int((config or {}).get("expand_budget") or DEFAULT_SEARCH_CONFIG["expand_budget"]),
    )


def expand_reasoning_layer(specs: List[dict], config: dict) -> List[dict]:
    if not specs:
        return []
    subj = str((specs[0] or {}).get("subject") or "").strip()
    options = get_reasoning_patterns(subj) or ["多步推导", "分类讨论", "变化分析", "构造反例", "等价转化", "综合推理"]
    return _expand_field(
        specs,
        field="reasoning",
        layer="reasoning",
        options=options,
        branch_factor=int((config or {}).get("reasoning_branch_factor") or DEFAULT_SEARCH_CONFIG["reasoning_branch_factor"]),
        budget=int((config or {}).get("expand_budget") or DEFAULT_SEARCH_CONFIG["expand_budget"]),
    )


def expand_trap_layer(specs: List[dict], config: dict) -> List[dict]:
    if not specs:
        return []
    subj = str((specs[0] or {}).get("subject") or "").strip()
    options = get_traps(subj) or ["边界遗漏", "条件方向错误", "概念混淆", "范围忽略"]
    return _expand_field(
        specs,
        field="trap",
        layer="trap",
        options=options,
        branch_factor=int((config or {}).get("trap_branch_factor") or DEFAULT_SEARCH_CONFIG["trap_branch_factor"]),
        budget=int((config or {}).get("expand_budget") or DEFAULT_SEARCH_CONFIG["expand_budget"]),
    )


def expand_surface_layer(specs: List[dict], config: dict) -> List[dict]:
    if not specs:
        return []
    subj = str((specs[0] or {}).get("subject") or "").strip()
    options = get_surfaces(subj) or ["综合题", "探究题", "应用题", "辨析题"]
    return _expand_field(
        specs,
        field="surface",
        layer="surface",
        options=options,
        branch_factor=int((config or {}).get("surface_branch_factor") or DEFAULT_SEARCH_CONFIG["surface_branch_factor"]),
        budget=int((config or {}).get("expand_budget") or DEFAULT_SEARCH_CONFIG["expand_budget"]),
    )


def beam_select(specs: List[dict], config: dict) -> List[dict]:
    bw = max(1, int((config or {}).get("beam_width") or DEFAULT_SEARCH_CONFIG["beam_width"]))
    scored: List[dict] = []
    for s in specs or []:
        if isinstance(s, dict):
            scored.append(dict(s))
    scored.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

    buckets: dict[str, List[dict]] = {}
    for item in scored:
        key = str(item.get("seed_tag") or item.get("skill") or item.get("reasoning") or item.get("spec_id") or "").strip()
        key = key or "__default__"
        buckets.setdefault(key, []).append(item)

    ordered_keys = sorted(
        buckets.keys(),
        key=lambda key: float(((buckets.get(key) or [{}])[0]).get("score") or 0.0),
        reverse=True,
    )

    selected: List[dict] = []
    used_ids: set[str] = set()
    while len(selected) < bw:
        progressed = False
        for key in ordered_keys:
            bucket = buckets.get(key) or []
            while bucket:
                candidate = bucket.pop(0)
                spec_id = str(candidate.get("spec_id") or "").strip()
                if spec_id and spec_id in used_ids:
                    continue
                if spec_id:
                    used_ids.add(spec_id)
                selected.append(candidate)
                progressed = True
                break
            if len(selected) >= bw:
                break
        if not progressed:
            break

    if len(selected) < bw:
        for item in scored:
            spec_id = str(item.get("spec_id") or "").strip()
            if spec_id and spec_id in used_ids:
                continue
            if spec_id:
                used_ids.add(spec_id)
            selected.append(item)
            if len(selected) >= bw:
                break
    return selected[:bw]
