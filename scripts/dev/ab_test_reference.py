from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "artifacts" / "reference_ab_test.json"

from backend.database.engine import init_db
from backend.generation.question_library.generation import (
    analyze_reference_questions,
    build_source_pack,
    collect_reference_questions,
    enrich_source_pack_with_reference,
    generate_questions,
)

DIFFICULTY_RANKS = {
    "基础": 1,
    "简单": 1,
    "较易": 1,
    "偏易": 1,
    "易": 1,
    "中等": 2,
    "中档": 2,
    "中等偏难": 3,
    "较难": 3,
    "偏难": 3,
    "困难": 4,
    "难": 4,
}


def _safe_mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return round(float(statistics.mean(values)), 3)


def _difficulty_rank(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    if text in DIFFICULTY_RANKS:
        return DIFFICULTY_RANKS[text]
    for key, rank in DIFFICULTY_RANKS.items():
        if key in text:
            return rank
    return 0


def _difficulty_match(target: str, estimate: str) -> bool:
    target_rank = _difficulty_rank(target)
    estimate_rank = _difficulty_rank(estimate)
    if target_rank <= 0 or estimate_rank <= 0:
        return str(target or "").strip() == str(estimate or "").strip()
    return abs(target_rank - estimate_rank) <= 1


def _question_preview(items: List[dict]) -> List[dict]:
    out: List[dict] = []
    for item in items[:3]:
        if not isinstance(item, dict):
            continue
        judge = item.get("judge") if isinstance(item.get("judge"), dict) else {}
        out.append(
            {
                "question_id": str(item.get("question_id") or "").strip(),
                "stem_preview": str(item.get("stem") or "").strip()[:180],
                "judge_score": int(judge.get("overall_score") or 0),
                "difficulty_estimate": str(judge.get("difficulty_estimate") or "").strip(),
                "verdict": str(judge.get("verdict") or "").strip(),
            }
        )
    return out


async def _run_group(args: argparse.Namespace, *, use_reference: bool) -> Dict[str, Any]:
    source_pack = await build_source_pack(
        study_markdown=str(args.study_markdown or ""),
        subject=str(args.subject or "").strip(),
        topic=str(args.topic or "").strip(),
        stream_reasoning=False,
        on_reasoning_event=None,
    )

    reference_questions: List[dict] = []
    reference_analysis: Dict[str, Any] = {}
    reference_result: Dict[str, Any] = {}

    if use_reference:
        reference_result = await collect_reference_questions(
            user_id=str(args.user_id or "").strip(),
            subject=str(args.subject or "").strip(),
            topic=str(args.topic or "").strip(),
            difficulty=str(args.difficulty or "").strip(),
            question_type=str(args.question_type or "").strip(),
            knowledge_point_ids=[],
            knowledge_points=[],
            desired_count=max(5, min(10, int(args.count or 3) + 3)),
            reference_source=str(args.reference_source or "any").strip() or "any",
            reference_year_range=str(args.reference_year_range or "all").strip() or "all",
        )
        reference_questions = [dict(item) for item in (reference_result.get("questions") or []) if isinstance(item, dict)]
        if reference_questions:
            reference_analysis = await analyze_reference_questions(
                subject=str(args.subject or "").strip(),
                topic=str(args.topic or "").strip(),
                difficulty=str(args.difficulty or "").strip(),
                question_type=str(args.question_type or "").strip(),
                reference_questions=reference_questions,
                stream_reasoning=False,
                on_reasoning_event=None,
            )
            source_pack = enrich_source_pack_with_reference(source_pack, reference_analysis, reference_questions)

    finals = await generate_questions(
        source_pack=source_pack,
        count=max(1, min(int(args.count or 3), 10)),
        difficulty=str(args.difficulty or "").strip(),
        question_type=str(args.question_type or "").strip(),
        on_stage_event=None,
        on_reasoning_event=None,
        on_candidate_accepted=None,
        on_generation_snapshot=None,
        stream_reasoning=False,
        config=None,
    )

    scores: List[float] = []
    difficulty_matches: List[float] = []
    for item in finals:
        if not isinstance(item, dict):
            continue
        judge = item.get("judge") if isinstance(item.get("judge"), dict) else {}
        score = float(judge.get("overall_score") or 0)
        scores.append(score)
        difficulty_matches.append(1.0 if _difficulty_match(str(args.difficulty or ""), str(judge.get("difficulty_estimate") or "")) else 0.0)

    return {
        "group": "reference" if use_reference else "control",
        "question_count": len([item for item in finals if isinstance(item, dict)]),
        "avg_judge_score": _safe_mean(scores),
        "difficulty_match_rate": _safe_mean(difficulty_matches),
        "reference": {
            "enabled": use_reference,
            "reference_count": len(reference_questions),
            "cache_hit": bool(reference_result.get("cache_hit")) if isinstance(reference_result, dict) else False,
            "degraded": bool(reference_result.get("degraded")) if isinstance(reference_result, dict) else False,
            "fallback_used": str(reference_result.get("fallback_used") or "").strip() if isinstance(reference_result, dict) else "",
            "source": str(reference_result.get("source") or "").strip() if isinstance(reference_result, dict) else "",
            "question_patterns": len(reference_analysis.get("question_patterns") or []) if isinstance(reference_analysis, dict) else 0,
            "representative_examples": len(reference_analysis.get("representative_examples") or []) if isinstance(reference_analysis, dict) else 0,
        },
        "questions": _question_preview([item for item in finals if isinstance(item, dict)]),
    }


def _aggregate_runs(group: str, runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "group": group,
        "rounds": len(runs),
        "avg_question_count": _safe_mean([float(run.get("question_count") or 0) for run in runs]),
        "avg_judge_score": _safe_mean([float(run.get("avg_judge_score") or 0) for run in runs]),
        "difficulty_match_rate": _safe_mean([float(run.get("difficulty_match_rate") or 0) for run in runs]),
        "reference_count": _safe_mean([float(((run.get("reference") or {}) if isinstance(run.get("reference"), dict) else {}).get("reference_count") or 0) for run in runs]),
        "cache_hit_rounds": int(
            sum(
                1
                for run in runs
                if bool(((run.get("reference") or {}) if isinstance(run.get("reference"), dict) else {}).get("cache_hit"))
            )
        ),
        "degraded_rounds": int(
            sum(
                1
                for run in runs
                if bool(((run.get("reference") or {}) if isinstance(run.get("reference"), dict) else {}).get("degraded"))
            )
        ),
        "samples": runs[: min(2, len(runs))],
    }


def _write_result(path_value: str, result: Dict[str, Any]) -> Path:
    output_path = Path(path_value).expanduser()
    if not output_path.is_absolute():
        output_path = (PROJECT_ROOT / output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


async def _main_async(args: argparse.Namespace) -> None:
    await init_db()

    rounds = max(1, min(int(args.rounds or 1), 10))
    control_runs: List[Dict[str, Any]] = []
    reference_runs: List[Dict[str, Any]] = []

    for _ in range(rounds):
        control_runs.append(await _run_group(args, use_reference=False))
        reference_runs.append(await _run_group(args, use_reference=True))

    control_summary = _aggregate_runs("control", control_runs)
    reference_summary = _aggregate_runs("reference", reference_runs)

    result = {
        "task": "reference_learning_ab_test",
        "subject": str(args.subject or "").strip(),
        "topic": str(args.topic or "").strip(),
        "difficulty": str(args.difficulty or "").strip(),
        "question_type": str(args.question_type or "").strip(),
        "count": max(1, min(int(args.count or 3), 10)),
        "rounds": rounds,
        "reference_source": str(args.reference_source or "any").strip() or "any",
        "reference_year_range": str(args.reference_year_range or "all").strip() or "all",
        "control": control_summary,
        "reference": reference_summary,
        "delta": {
            "avg_judge_score": round(float(reference_summary.get("avg_judge_score") or 0) - float(control_summary.get("avg_judge_score") or 0), 3),
            "difficulty_match_rate": round(float(reference_summary.get("difficulty_match_rate") or 0) - float(control_summary.get("difficulty_match_rate") or 0), 3),
            "avg_question_count": round(float(reference_summary.get("avg_question_count") or 0) - float(control_summary.get("avg_question_count") or 0), 3),
        },
    }

    output_path = _write_result(str(args.output or DEFAULT_OUTPUT_PATH), result)
    result["output_path"] = str(output_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ab_test_reference", description="Compare AI question generation quality with and without reference learning.")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--difficulty", default="中等")
    parser.add_argument("--question-type", default="")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--user-id", default="")
    parser.add_argument("--study-markdown", default="")
    parser.add_argument("--reference-source", choices=["any", "gaokao", "mock", "joint"], default="any")
    parser.add_argument("--reference-year-range", choices=["all", "3", "5"], default="all")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
