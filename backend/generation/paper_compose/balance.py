from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Sequence

StemFingerprintFn = Callable[[str], str]


def _qid(question: Dict[str, Any]) -> str:
    return str(question.get("question_id") or "").strip()


def _quality(question: Dict[str, Any]) -> int:
    try:
        return int(question.get("quality_score") or 0)
    except (TypeError, ValueError):
        return 0


def _difficulty_bucket(label: Any, value: Any = None) -> str:
    try:
        if value is not None and str(value).strip():
            v = float(value)
            if v <= 0.39:
                return "hard"
            if v <= 0.69:
                return "medium"
            return "easy"
    except (TypeError, ValueError):
        pass

    raw = str(label or "").strip().lower()
    if not raw:
        return ""
    if raw in {"hard", "difficult"} or "难" in raw:
        return "hard"
    if raw in {"medium", "mid"} or "中" in raw or "适" in raw:
        return "medium"
    if raw in {"easy", "simple"} or "易" in raw or "简" in raw:
        return "easy"
    return ""


def _slot_attr(slot: Any, name: str) -> Any:
    if isinstance(slot, dict):
        return slot.get(name)
    return getattr(slot, name, None)


def _slot_question_type(slot: Any) -> str:
    return str(_slot_attr(slot, "question_type") or _slot_attr(slot, "question_type_raw") or "").strip()


def _slot_difficulty(slot: Any) -> str:
    return str(_slot_attr(slot, "difficulty") or "").strip()


def _slot_index(slot: Any) -> int:
    try:
        return int(_slot_attr(slot, "index") or 0)
    except (TypeError, ValueError):
        return 0


def _question_type(question: Dict[str, Any]) -> str:
    return str(question.get("type") or question.get("question_type") or "").strip()


def _knowledge_points(question: Dict[str, Any]) -> List[str]:
    raw = question.get("knowledge_points")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x or "").strip()]
    raw_text = str(question.get("knowledge_point") or "").strip()
    return [raw_text] if raw_text else []


def _primary_kp(question: Dict[str, Any]) -> str:
    points = _knowledge_points(question)
    return points[0] if points else ""


def _stem_fp(question: Dict[str, Any], stem_fingerprint: StemFingerprintFn) -> str:
    cached = str(question.get("stem_fingerprint") or "").strip()
    if cached:
        return cached
    return stem_fingerprint(str(question.get("stem") or ""))


def _matches_slot_type(question: Dict[str, Any], slot_type: str) -> bool:
    if not slot_type:
        return True
    q_type = _question_type(question)
    return not q_type or q_type == slot_type


def _candidate_score(
    question: Dict[str, Any],
    *,
    slot_bucket: str,
    slot_type: str,
    repeated_kps: set[str],
) -> tuple[int, int, int, int, str]:
    q_bucket = _difficulty_bucket(question.get("difficulty"), question.get("difficulty_value"))
    difficulty_match = 1 if not slot_bucket or not q_bucket or q_bucket == slot_bucket else 0
    type_match = 1 if _matches_slot_type(question, slot_type) else 0
    kp = _primary_kp(question)
    kp_diverse = 1 if not kp or kp not in repeated_kps else 0
    return (difficulty_match, type_match, kp_diverse, _quality(question), _qid(question))


def _find_replacement(
    *,
    candidates: Sequence[Dict[str, Any]],
    current: Dict[str, Any],
    slot_bucket: str,
    slot_type: str,
    selected_ids: set[str],
    used_ids: set[str],
    fp_counts: Counter[str],
    repeated_kps: set[str],
    min_quality_score: int,
    stem_fingerprint: StemFingerprintFn,
    reasons: Sequence[str],
) -> Optional[Dict[str, Any]]:
    old_fp = _stem_fp(current, stem_fingerprint)
    options: List[Dict[str, Any]] = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_id = _qid(candidate)
        if not candidate_id or candidate_id in selected_ids or candidate_id in used_ids:
            continue
        if not _matches_slot_type(candidate, slot_type):
            continue
        if _quality(candidate) < min_quality_score:
            continue

        candidate_bucket = _difficulty_bucket(candidate.get("difficulty"), candidate.get("difficulty_value"))
        if "difficulty_mismatch" in reasons and slot_bucket and candidate_bucket and candidate_bucket != slot_bucket:
            continue

        candidate_fp = _stem_fp(candidate, stem_fingerprint)
        if candidate_fp and candidate_fp != old_fp and fp_counts.get(candidate_fp, 0) > 0:
            continue
        if "duplicate_stem" in reasons and candidate_fp and candidate_fp == old_fp:
            continue

        if "knowledge_repeat" in reasons:
            candidate_kp = _primary_kp(candidate)
            if candidate_kp and candidate_kp in repeated_kps:
                continue

        options.append(candidate)

    if not options:
        return None

    options.sort(
        key=lambda question: _candidate_score(
            question,
            slot_bucket=slot_bucket,
            slot_type=slot_type,
            repeated_kps=repeated_kps,
        ),
        reverse=True,
    )
    return options[0]


def apply_balance_corrections(
    slot_results: Sequence[Dict[str, Any]],
    *,
    used_ids: Optional[set[str]] = None,
    stem_fingerprint: StemFingerprintFn,
    min_quality_score: int = 0,
    max_replacements: int = 50,
) -> Dict[str, Any]:
    """Mutate slot selections to fix obvious paper-level balance issues.

    The pass stays deterministic and local: it only swaps in already fetched candidates
    from the same slot and never calls a crawler or LLM.
    """

    used_ids = used_ids or set()
    min_quality_score = max(0, min(int(min_quality_score or 0), 100))
    max_replacements = max(0, min(int(max_replacements or 0), 200))

    selected: List[Dict[str, Any]] = []
    for slot_result in slot_results:
        items = slot_result.get("selected") if isinstance(slot_result, dict) else None
        if isinstance(items, list):
            selected.extend([q for q in items if isinstance(q, dict)])

    selected_ids = {_qid(question) for question in selected if _qid(question)}
    fp_counts: Counter[str] = Counter(
        fp for fp in (_stem_fp(question, stem_fingerprint) for question in selected) if fp
    )
    kp_counts: Counter[str] = Counter(kp for kp in (_primary_kp(question) for question in selected) if kp)
    kp_repeat_threshold = max(2, (len(selected) + 3) // 4)
    repeated_kps = {kp for kp, count in kp_counts.items() if count > kp_repeat_threshold}

    seen_fps: set[str] = set()
    seen_repeated_kps: Counter[str] = Counter()
    replacements: List[Dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()

    for slot_result in slot_results:
        if len(replacements) >= max_replacements:
            break
        slot = slot_result.get("slot") if isinstance(slot_result, dict) else None
        slot_selected = slot_result.get("selected") if isinstance(slot_result, dict) else None
        candidates = slot_result.get("candidates") if isinstance(slot_result, dict) else None
        if not isinstance(slot_selected, list) or not isinstance(candidates, list):
            continue

        slot_bucket = _difficulty_bucket(_slot_difficulty(slot))
        slot_type = _slot_question_type(slot)

        for index, question in enumerate(list(slot_selected)):
            if len(replacements) >= max_replacements:
                break
            if not isinstance(question, dict):
                continue

            reasons: List[str] = []
            q_bucket = _difficulty_bucket(question.get("difficulty"), question.get("difficulty_value"))
            if slot_bucket and q_bucket and q_bucket != slot_bucket:
                reasons.append("difficulty_mismatch")

            fp = _stem_fp(question, stem_fingerprint)
            if fp and fp_counts.get(fp, 0) > 1 and fp in seen_fps:
                reasons.append("duplicate_stem")
            elif fp:
                seen_fps.add(fp)

            primary_kp = _primary_kp(question)
            if primary_kp and primary_kp in repeated_kps:
                seen_repeated_kps[primary_kp] += 1
                if seen_repeated_kps[primary_kp] > kp_repeat_threshold:
                    reasons.append("knowledge_repeat")

            if not reasons:
                continue

            replacement = _find_replacement(
                candidates=candidates,
                current=question,
                slot_bucket=slot_bucket,
                slot_type=slot_type,
                selected_ids=selected_ids,
                used_ids=used_ids,
                fp_counts=fp_counts,
                repeated_kps=repeated_kps,
                min_quality_score=min_quality_score,
                stem_fingerprint=stem_fingerprint,
                reasons=reasons,
            )
            if replacement is None:
                continue

            old_id = _qid(question)
            new_id = _qid(replacement)
            old_fp = _stem_fp(question, stem_fingerprint)
            new_fp = _stem_fp(replacement, stem_fingerprint)
            old_kp = _primary_kp(question)
            new_kp = _primary_kp(replacement)

            slot_selected[index] = replacement
            if old_id:
                selected_ids.discard(old_id)
            if new_id:
                selected_ids.add(new_id)
            if old_fp:
                fp_counts[old_fp] = max(0, fp_counts.get(old_fp, 0) - 1)
            if new_fp:
                fp_counts[new_fp] += 1
                seen_fps.add(new_fp)
            if old_kp:
                kp_counts[old_kp] = max(0, kp_counts.get(old_kp, 0) - 1)
            if new_kp:
                kp_counts[new_kp] += 1

            for reason in reasons:
                reason_counts[reason] += 1
            replacements.append(
                {
                    "slotIndex": _slot_index(slot),
                    "old": old_id,
                    "new": new_id,
                    "reasons": reasons,
                }
            )

    return {
        "enabled": True,
        "totalReplaced": len(replacements),
        "difficultyReplaced": int(reason_counts.get("difficulty_mismatch", 0)),
        "duplicateStemReplaced": int(reason_counts.get("duplicate_stem", 0)),
        "knowledgeRepeatReplaced": int(reason_counts.get("knowledge_repeat", 0)),
        "replacements": replacements[:50],
    }
