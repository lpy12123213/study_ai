from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Iterable

DIFFICULTY_LEVELS = ("基础", "中等", "困难", "压轴")

_DIFFICULTY_ALIASES = {
    "简单": "基础",
    "容易": "基础",
    "基础": "基础",
    "中等": "中等",
    "适中": "中等",
    "偏难": "困难",
    "较难": "困难",
    "困难": "困难",
    "难": "困难",
    "压轴": "压轴",
    "高考压轴": "压轴",
}


def normalize_difficulty(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "").strip())
    if not text:
        return ""
    if text in _DIFFICULTY_ALIASES:
        return _DIFFICULTY_ALIASES[text]
    for alias, normalized in sorted(_DIFFICULTY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in text:
            return normalized
    return ""


def difficulty_mismatch(*, target: Any, assessed: Any, evidence_count: int = 0) -> dict:
    """Return an evidence-gated penalty for a mismatch of difficulty bands.

    Difficulty is a semantic judgement, so a model label is never allowed into
    fitness without at least one grounded candidate excerpt.  A one-band miss
    costs 8 points, rising to a maximum of 24 points.
    """

    target_label = normalize_difficulty(target)
    assessed_label = normalize_difficulty(assessed)
    grounded = int(evidence_count or 0) > 0
    if not target_label or not assessed_label or not grounded:
        return {
            "target": target_label,
            "assessed": assessed_label,
            "gap": 0,
            "penalty": 0.0,
            "evidence_count": max(0, int(evidence_count or 0)),
            "counted": False,
        }
    gap = abs(DIFFICULTY_LEVELS.index(target_label) - DIFFICULTY_LEVELS.index(assessed_label))
    return {
        "target": target_label,
        "assessed": assessed_label,
        "gap": gap,
        "penalty": round(min(0.24, 0.08 * gap), 4),
        "evidence_count": max(0, int(evidence_count or 0)),
        "counted": True,
    }


def _compact(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def normalize_solution_fingerprint(value: Any) -> list[dict]:
    """Normalize an abstract reference-solution fingerprint.

    Only short concept labels survive.  Full reference questions, calculations,
    solution prose and numeric constants are neither needed nor retained.
    """

    raw_items = value if isinstance(value, list) else []
    out: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_items[:12]):
        if not isinstance(raw, dict):
            continue
        unit_id = re.sub(r"[^a-z0-9_\-]", "", str(raw.get("id") or f"step_{index + 1}").lower())[:64]
        if not unit_id or unit_id in seen:
            continue
        concepts: list[str] = []
        for concept in raw.get("concepts") or []:
            text = str(concept or "").strip()
            compact = _compact(text)
            # Concept labels are intentionally short and abstract.  Requiring
            # two visible characters also avoids punctuation-only matches.
            if 2 <= len(compact) <= 32 and text not in concepts:
                concepts.append(text[:40])
        if len(concepts) < 2:
            continue
        try:
            weight = float(raw.get("weight") or 1.0)
        except (TypeError, ValueError):
            weight = 1.0
        out.append({"id": unit_id, "concepts": concepts[:6], "weight": round(max(0.5, min(3.0, weight)), 2)})
        seen.add(unit_id)
    return out


def normalize_evolution_evaluation(value: Any) -> dict:
    raw = value if isinstance(value, dict) else {}
    try:
        threshold = float(raw.get("max_solution_similarity", 0.58))
    except (TypeError, ValueError):
        threshold = 0.58
    return {
        "reference_id": re.sub(r"[^a-zA-Z0-9_.\-]", "", str(raw.get("reference_id") or ""))[:96],
        "solution_fingerprint": normalize_solution_fingerprint(raw.get("solution_fingerprint")),
        "max_solution_similarity": round(max(0.35, min(0.9, threshold)), 4),
    }


def solution_fingerprint_similarity(*, solution_text: Any, fingerprint: Any) -> dict:
    units = normalize_solution_fingerprint(fingerprint)
    compact_solution = _compact(solution_text)
    if not compact_solution or not units:
        return {"score": 0.0, "matched_ids": [], "matched_weight": 0.0, "total_weight": 0.0}

    total_weight = sum(float(unit["weight"]) for unit in units)
    matched: list[tuple[str, float, int]] = []
    for unit in units:
        positions = [
            compact_solution.find(_compact(concept))
            for concept in unit["concepts"]
            if _compact(concept) and _compact(concept) in compact_solution
        ]
        required = max(2, math.ceil(len(unit["concepts"]) / 2))
        if len(positions) >= required:
            matched.append((str(unit["id"]), float(unit["weight"]), min(positions)))

    matched_weight = sum(item[1] for item in matched)
    coverage = matched_weight / total_weight if total_weight else 0.0
    if len(matched) < 2:
        ordered_ratio = 0.0
    else:
        ordered_pairs = sum(1 for left, right in zip(matched, matched[1:]) if left[2] <= right[2])
        ordered_ratio = ordered_pairs / (len(matched) - 1)
    score = 0.8 * coverage + 0.2 * ordered_ratio * coverage
    return {
        "score": round(max(0.0, min(1.0, score)), 4),
        "matched_ids": [item[0] for item in matched],
        "matched_weight": round(matched_weight, 2),
        "total_weight": round(total_weight, 2),
    }


def imitation_penalty(
    *,
    local_similarity: float,
    threshold: float,
    supervisor_similarity: float = 0.0,
    supervisor_evidence_count: int = 0,
    supervisor_matched_ids: Iterable[str] = (),
) -> dict:
    """Combine deterministic and independently supervised similarity evidence."""

    local = max(0.0, min(1.0, float(local_similarity or 0.0)))
    supervisor = max(0.0, min(1.0, float(supervisor_similarity or 0.0)))
    grounded_supervisor = int(supervisor_evidence_count or 0) > 0 and bool(list(supervisor_matched_ids or []))
    score = max(local, supervisor if grounded_supervisor else 0.0)
    limit = max(0.35, min(0.9, float(threshold or 0.58)))
    if score <= limit:
        penalty = 0.0
    else:
        excess_ratio = (score - limit) / max(0.01, 1.0 - limit)
        penalty = min(0.30, 0.08 + 0.22 * excess_ratio)
    return {
        "similarity": round(score, 4),
        "threshold": round(limit, 4),
        "penalty": round(penalty, 4),
        "local_similarity": round(local, 4),
        "supervisor_similarity": round(supervisor, 4) if grounded_supervisor else 0.0,
        "supervisor_evidence_count": max(0, int(supervisor_evidence_count or 0)),
        "counted_supervisor": grounded_supervisor,
    }


def evaluate_evolution_penalties(
    *,
    draft: dict,
    target_difficulty: Any,
    assessed_difficulty: Any,
    difficulty_evidence: Iterable[Any],
    evaluation: Any,
    supervisor_similarity: float = 0.0,
    supervisor_similarity_evidence: Iterable[Any] = (),
    supervisor_matched_ids: Iterable[str] = (),
) -> dict:
    contract = normalize_evolution_evaluation(evaluation)
    difficulty_evidence_list = list(difficulty_evidence or [])
    similarity_evidence_list = list(supervisor_similarity_evidence or [])
    solution_text = "\n".join(
        [str((draft or {}).get("answer") or ""), str((draft or {}).get("analysis") or "")]
    )
    local = solution_fingerprint_similarity(
        solution_text=solution_text,
        fingerprint=contract["solution_fingerprint"],
    )
    difficulty = difficulty_mismatch(
        target=target_difficulty,
        assessed=assessed_difficulty,
        evidence_count=len(difficulty_evidence_list),
    )
    imitation = imitation_penalty(
        local_similarity=float(local["score"]),
        threshold=float(contract["max_solution_similarity"]),
        supervisor_similarity=supervisor_similarity,
        supervisor_evidence_count=len(similarity_evidence_list),
        supervisor_matched_ids=supervisor_matched_ids,
    )
    imitation.update(
        {
            "reference_id": contract["reference_id"],
            "matched_ids": list(local["matched_ids"]),
            "supervisor_matched_ids": list(supervisor_matched_ids or [])[:12],
            "local_match": local,
        }
    )
    total = min(0.54, float(difficulty["penalty"]) + float(imitation["penalty"]))
    return {"difficulty": difficulty, "imitation": imitation, "total": round(total, 4)}
