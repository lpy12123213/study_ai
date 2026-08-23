from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, List

FATAL_DEFECTS = {"wrong_answer", "missing_condition", "symbol_reversal"}


def inject_defect_variants(draft: dict) -> List[dict]:
    """Build reproducible supervision probes without sending them to a model."""

    base = copy.deepcopy(draft or {})
    variants: list[dict] = []

    def add(defect: str, expected: str, mutate) -> None:  # noqa: ANN001
        item = copy.deepcopy(base)
        mutate(item)
        variants.append({"defect": defect, "expected_issue_code": expected, "draft": item})

    add("wrong_answer", "answer_incorrect", lambda item: item.update(answer=f"{item.get('answer', '')}（错误变体）"))
    add(
        "missing_condition",
        "conditions_insufficient",
        lambda item: item.update(stem=re.sub(r"[，,；;][^，,；;。.!?]*[。.!?]?$", "。", str(item.get("stem") or ""))),
    )
    add(
        "symbol_reversal",
        "answer_incorrect",
        lambda item: item.update(
            analysis=str(item.get("analysis") or "").replace("\\le", "\\ge", 1).replace("<", ">", 1)
        ),
    )
    add("method_leak", "method_leak", lambda item: item.update(stem="请直接使用题面给出的完整方法：" + str(item.get("stem") or "")))

    def pseudo_transfer(item: dict) -> None:
        packet = item.get("intuition_packet") if isinstance(item.get("intuition_packet"), dict) else {}
        packet = copy.deepcopy(packet)
        stages = packet.get("stages") if isinstance(packet.get("stages"), list) else []
        for stage in stages:
            if isinstance(stage, dict) and str(stage.get("stage") or "") == "transfer":
                stage["prompt"] = "只把原题中的数字 2 改成 3，重复同样步骤。"
        packet["stages"] = stages
        item["intuition_packet"] = packet

    add("pseudo_transfer", "transfer_invalid", pseudo_transfer)
    add(
        "redundant_condition",
        "redundant_condition",
        lambda item: item.update(stem=str(item.get("stem") or "") + " 已知条件与上述条件完全相同。"),
    )
    add(
        "number_only_copy",
        "original_number_only",
        lambda item: item.update(stem=re.sub(r"\d+", lambda match: str(int(match.group(0)) + 1), str(item.get("stem") or ""))),
    )
    return variants


def score_supervision_benchmark(rows: Iterable[dict]) -> Dict[str, Any]:
    items = [dict(row) for row in rows if isinstance(row, dict)]
    defects = [item for item in items if str(item.get("defect") or "") != "good"]
    fatal = [item for item in defects if str(item.get("defect") or "") in FATAL_DEFECTS]

    def detected(item: dict) -> bool:
        expected = str(item.get("expected_issue_code") or "").strip()
        predicted = {str(code or "").strip() for code in (item.get("predicted_issue_codes") or [])}
        return expected in predicted

    fatal_recall = sum(1 for item in fatal if detected(item)) / max(1, len(fatal))
    false_allow = sum(1 for item in defects if bool(item.get("pass"))) / max(1, len(defects))
    good_scores = [float(item.get("score") or 0.0) for item in items if str(item.get("defect") or "") == "good"]
    pair_count = 0
    correct_pairs = 0
    for good_score in good_scores:
        for defective in defects:
            pair_count += 1
            if good_score > float(defective.get("score") or 0.0):
                correct_pairs += 1
    ranking_accuracy = correct_pairs / max(1, pair_count)
    unsupported_fitness_labels = sum(
        1
        for item in items
        if bool(item.get("fitness_counted")) and not list(item.get("evidence") or [])
    )
    return {
        "fatal_defect_recall": round(fatal_recall, 4),
        "false_allow_rate": round(false_allow, 4),
        "ranking_accuracy": round(ranking_accuracy, 4),
        "unsupported_fitness_labels": unsupported_fitness_labels,
        "passed": fatal_recall >= 0.95
        and false_allow <= 0.02
        and ranking_accuracy >= 0.85
        and unsupported_fitness_labels == 0,
    }
