from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.llm.client import is_llm_configured
from backend.generation.question_library.beam_search import (
    beam_select,
    expand_reasoning_layer,
    expand_skill_layer,
    expand_surface_layer,
    expand_trap_layer,
    seed_root_specs,
    seed_root_specs_from_brainstorm,
)
from backend.generation.question_library.brainstorm import brainstorm_creative_seeds
from backend.generation.question_library.diagram_integration import enrich_drafts_with_diagrams
from backend.generation.question_library.draft_realization import (
    build_generation_messages,
    build_regenerate_section_messages,
    realize_drafts,
    regenerate_question_section,
)
from backend.generation.question_library.gen_common import DEFAULT_SEARCH_CONFIG, _clip_unique
from backend.generation.question_library.gen_utils import (
    CandidateAcceptedHandler,
    GenerationSnapshotHandler,
    ReasoningEventHandler,
    StageEventHandler,
    _as_bool,
    _difficulty_mismatch_penalty,
    _emit_callback,
    _emit_stage_event,
    _resolve_runtime_search_config,
    _summarize_candidate_sample,
    build_ai_question_id,
)
from backend.generation.question_library.judging import check_ambiguity, judge_draft, refine_draft, solve_draft
from backend.generation.question_library.reference_analysis import analyze_reference_questions, enrich_source_pack_with_reference
from backend.generation.question_library.reference_crawl import collect_reference_questions
from backend.generation.question_library.selection import select_final
from backend.generation.question_library.source_pack import build_source_pack
from backend.generation.question_library.curriculum_context import (
    build_curriculum_context,
    enrich_source_pack_with_curriculum,
)
from backend.generation.question_library.spec_scoring import score_spec

logger = get_logger(__name__)

__all__ = [
    # Orchestrator
    "generate_questions",
    # Source pack + reference pipeline (used by API + CLI)
    "build_source_pack",
    "collect_reference_questions",
    "analyze_reference_questions",
    "enrich_source_pack_with_reference",
    "build_curriculum_context",
    "enrich_source_pack_with_curriculum",
    # Spec search utilities (used by tests)
    "seed_root_specs",
    "expand_skill_layer",
    "expand_reasoning_layer",
    "expand_trap_layer",
    "expand_surface_layer",
    "score_spec",
    "beam_select",
    # Draft realization utilities (used by API)
    "realize_drafts",
    "regenerate_question_section",
    "build_generation_messages",
    "build_regenerate_section_messages",
    # Judge pipeline (used by generate_questions)
    "solve_draft",
    "check_ambiguity",
    "judge_draft",
    "refine_draft",
    # Final selection
    "select_final",
    # Misc
    "build_ai_question_id",
]


async def generate_questions(
    *,
    source_pack: dict,
    count: int,
    difficulty: str,
    question_type: str,
    user_id: str = "",
    on_stage_event: StageEventHandler = None,
    on_reasoning_event: ReasoningEventHandler = None,
    on_candidate_accepted: CandidateAcceptedHandler = None,
    on_generation_snapshot: GenerationSnapshotHandler = None,
    stream_reasoning: bool = False,
    config: Optional[dict] = None,
) -> List[dict]:
    cfg = _resolve_runtime_search_config(config, count=count)
    cfg["target_difficulty"] = str(difficulty or "").strip()

    # Ensure source_pack contains distilled guidance for novelty/template avoidance.
    if not isinstance(source_pack, dict):
        source_pack = {}
    if not source_pack.get("skills") and not source_pack.get("forbidden_patterns"):
        try:
            source_pack = await build_source_pack(
                str(source_pack.get("study_markdown") or ""),
                str(source_pack.get("subject") or ""),
                str(source_pack.get("topic") or ""),
                stream_reasoning=stream_reasoning,
                on_reasoning_event=on_reasoning_event,
            )
        except Exception:
            logger.warning(
                "question_library_source_pack_build_failed",
                extra={
                    "user_id": str(user_id or "").strip(),
                    "subject": str(source_pack.get("subject") or "").strip(),
                    "topic": str(source_pack.get("topic") or "").strip(),
                },
                exc_info=True,
            )

    if not source_pack.get("question_requirements") and not source_pack.get("prerequisites"):
        try:
            curriculum = await build_curriculum_context(
                subject=str(source_pack.get("subject") or "").strip(),
                topic=str(source_pack.get("topic") or "").strip(),
                knowledge_points=list(source_pack.get("knowledge_points") or []),
                grade_id=str(source_pack.get("grade_id") or "").strip(),
                textbook_version_id=str(source_pack.get("textbook_version_id") or "").strip(),
                study_markdown=str(source_pack.get("study_markdown") or "").strip(),
                stream_reasoning=stream_reasoning,
                on_reasoning_event=on_reasoning_event,
            )
            source_pack = enrich_source_pack_with_curriculum(source_pack, curriculum)
        except Exception:
            logger.warning(
                "question_library_curriculum_context_build_failed",
                extra={
                    "user_id": str(user_id or "").strip(),
                    "subject": str(source_pack.get("subject") or "").strip(),
                    "topic": str(source_pack.get("topic") or "").strip(),
                },
                exc_info=True,
            )

    beam_width = max(1, int(cfg.get("beam_width") or DEFAULT_SEARCH_CONFIG["beam_width"]))
    search_beam_width = max(beam_width, int(max(1, count or 1) * 2))

    def _score_and_beam(items: List[dict]) -> List[dict]:
        scored = [score_spec(s, source_pack, cfg) for s in items if isinstance(s, dict)]
        return beam_select(scored, {"beam_width": search_beam_width})

    root_specs: List[dict] = []
    root_beam: List[dict] = []
    skill_specs: List[dict] = []
    skill_beam: List[dict] = []
    reasoning_specs: List[dict] = []
    reasoning_beam: List[dict] = []
    trap_specs: List[dict] = []
    trap_beam: List[dict] = []
    surface_specs: List[dict] = []
    specs: List[dict] = []

    try:
        root_specs = seed_root_specs(source_pack, count=count, difficulty=difficulty, question_type=question_type)

        enable_brainstorm = _as_bool(cfg.get("enable_brainstorm"), default=bool(DEFAULT_SEARCH_CONFIG.get("enable_brainstorm")))
        if enable_brainstorm and is_llm_configured():
            try:
                seed_count = int(cfg.get("brainstorm_seed_count") or DEFAULT_SEARCH_CONFIG.get("brainstorm_seed_count") or 8)
            except (TypeError, ValueError):
                seed_count = 8
            seed_count = max(4, min(seed_count, 12))
            try:
                brainstorm_seeds = await brainstorm_creative_seeds(
                    source_pack,
                    seed_count=seed_count,
                    stream_reasoning=stream_reasoning,
                    on_reasoning_event=on_reasoning_event,
                )
            except (RuntimeError, AssertionError):
                brainstorm_seeds = []
            except Exception:
                logger.warning("question_library_brainstorm_failed", exc_info=True)
                brainstorm_seeds = []

            if brainstorm_seeds:
                root_specs = seed_root_specs_from_brainstorm(
                    source_pack,
                    brainstorm_seeds,
                    count=count,
                    difficulty=difficulty,
                    question_type=question_type,
                )

            await _emit_stage_event(
                on_stage_event,
                phase="brainstorm",
                label="创意发散",
                progress=10.0,
                stats={
                    "enabled": True,
                    "seed_count": len(brainstorm_seeds or []),
                    "kept_root_specs": len(root_specs or []),
                },
                sample={"seed_tag": str((root_specs[0] or {}).get("seed_tag") or "").strip()} if root_specs else None,
            )
        else:
            await _emit_stage_event(
                on_stage_event,
                phase="brainstorm",
                label="创意发散",
                progress=10.0,
                stats={"enabled": False},
            )

        root_beam = _score_and_beam(root_specs)
        skill_specs = expand_skill_layer(root_beam, cfg)
        skill_beam = _score_and_beam(skill_specs)
        reasoning_specs = expand_reasoning_layer(skill_beam, cfg)
        reasoning_beam = _score_and_beam(reasoning_specs)
        trap_specs = expand_trap_layer(reasoning_beam, cfg)
        trap_beam = _score_and_beam(trap_specs)
        surface_specs = expand_surface_layer(trap_beam, cfg)
        specs = _score_and_beam(surface_specs)
    except Exception:
        logger.exception(
            "question_library_spec_search_failed",
            extra={
                "subject": str((source_pack or {}).get("subject") or "").strip(),
                "topic": str((source_pack or {}).get("topic") or "").strip(),
                "difficulty": str(difficulty or "").strip(),
                "question_type": str(question_type or "").strip(),
            },
        )
        raise

    per_spec = max(1, min(int(cfg.get("drafts_per_spec") or DEFAULT_SEARCH_CONFIG["drafts_per_spec"]), 4))
    max_specs = max(1, min(int(count or 1) * 3, max(4, search_beam_width)))
    specs = specs[:max_specs]

    await _emit_stage_event(
        on_stage_event,
        phase="spec_search",
        label="规格搜索",
        progress=20.0,
        stats={
            "root_specs": len(root_specs),
            "root_kept": len(root_beam),
            "skill_expanded": len(skill_specs),
            "reasoning_expanded": len(reasoning_specs),
            "trap_expanded": len(trap_specs),
            "surface_expanded": len(surface_specs),
            "kept_specs": len(specs),
            "search_beam_width": search_beam_width,
            "sample_seed_tags": _clip_unique([str((s or {}).get("seed_tag") or "") for s in specs], 4),
            "sample_skills": _clip_unique([str((s or {}).get("skill") or "") for s in specs], 4),
        },
        sample=_summarize_candidate_sample(specs[0]) if specs else None,
    )

    raw_candidates: List[dict] = []
    realize_failures = 0
    realize_sem = asyncio.Semaphore(max(1, int(cfg.get("max_concurrent_realize") or 4)))

    async def _realize_spec(spec: dict) -> tuple[list[dict], Optional[Exception]]:
        async with realize_sem:
            try:
                ds = await realize_drafts(
                    spec,
                    source_pack=source_pack,
                    n=per_spec,
                    stream_reasoning=stream_reasoning,
                    on_reasoning_event=on_reasoning_event,
                )
                out = [dict(item) for item in (ds or []) if isinstance(item, dict)]
                return out, None
            except RuntimeError as exc:
                return [], exc
            except Exception as exc:
                logger.warning("question_library_realize_drafts_unexpected_failed", exc_info=True)
                return [], exc

    realize_results = await asyncio.gather(*[_realize_spec(spec) for spec in specs]) if specs else []
    for spec, (drafts, error) in zip(specs, realize_results):
        if error is not None:
            realize_failures += 1
            logger.warning(
                "question_library_realize_drafts_failed",
                extra={
                    "spec_id": str((spec or {}).get("spec_id") or "").strip(),
                    "topic": str((spec or {}).get("topic") or "").strip(),
                    "error": str(error),
                },
            )
            continue
        raw_candidates.extend(drafts)

    await _emit_stage_event(
        on_stage_event,
        phase="draft_realization",
        label="草稿生成",
        progress=55.0,
        stats={
            "spec_count": len(specs),
            "drafts_per_spec": per_spec,
            "draft_count": len(raw_candidates),
            "realize_failures": realize_failures,
            "empty_specs": max(
                0,
                len(specs)
                - len(
                    {
                        str((d or {}).get("spec_id") or "").strip()
                        for d in raw_candidates
                        if isinstance(d, dict)
                    }
                ),
            ),
        },
        sample=_summarize_candidate_sample(raw_candidates[0]) if raw_candidates else None,
    )
    await _emit_callback(
        on_generation_snapshot,
        {
            "phase": "draft_realization",
            "raw_candidates": [dict(item) for item in raw_candidates],
            "accepted": [],
            "stats": {"draft_count": len(raw_candidates), "realize_failures": realize_failures},
        },
    )

    if not raw_candidates:
        return []

    # Stage: diagram generation (best-effort, subject-aware). Runs before judging so the judge
    # can see the final stem context (including any referenced figures).
    try:
        await _emit_stage_event(
            on_stage_event,
            phase="diagram_generation",
            label="配图生成",
            progress=60.0,
            stats={"enabled": True, "draft_count": len(raw_candidates)},
        )
        raw_candidates = await enrich_drafts_with_diagrams(
            raw_candidates,
            user_id=str(user_id or "").strip() or str((source_pack or {}).get("user_id") or "").strip() or "anonymous",
            source_pack=source_pack,
            stream_reasoning=stream_reasoning,
            on_reasoning_event=on_reasoning_event,
        )
        diagrams_total = 0
        for d in raw_candidates:
            if isinstance(d, dict) and isinstance(d.get("diagrams"), list):
                diagrams_total += len([x for x in (d.get("diagrams") or []) if isinstance(x, dict)])
        await _emit_stage_event(
            on_stage_event,
            phase="diagram_generation",
            label="配图生成",
            progress=65.0,
            stats={"draft_count": len(raw_candidates), "diagrams_total": diagrams_total},
            sample=_summarize_candidate_sample(raw_candidates[0]) if raw_candidates else None,
        )
    except Exception:
        # Never fail the whole pipeline just because diagrams are unavailable.
        logger.warning(
            "question_library_diagram_generation_failed",
            extra={"user_id": str(user_id or "").strip()},
            exc_info=True,
        )

    # Stage: solver + ambiguity + judge + optional repair.
    accepted: List[dict] = []
    judge_floor = int(cfg.get("judge_pass_score") or DEFAULT_SEARCH_CONFIG["judge_pass_score"])
    judge_require_pass_flag = _as_bool(cfg.get("judge_require_pass_flag"), default=False)
    solver_consensus_n = max(1, min(int(cfg.get("solver_consensus_n") or 1), 3))
    answer_mismatch_penalty = max(
        0, int(cfg.get("answer_mismatch_penalty") or DEFAULT_SEARCH_CONFIG["answer_mismatch_penalty"])
    )
    ambiguity_penalty_score = max(
        0, int(cfg.get("ambiguity_penalty_score") or DEFAULT_SEARCH_CONFIG["ambiguity_penalty_score"])
    )
    max_repairs = max(0, int(cfg.get("max_repair_rounds") or 0))
    repair_band = max(0, int(cfg.get("repair_score_band") or DEFAULT_SEARCH_CONFIG["repair_score_band"]))
    repair_min_score = max(0, int(cfg.get("repair_min_score") or DEFAULT_SEARCH_CONFIG["repair_min_score"]))
    judged_total = 0
    repairs_attempted = 0
    reject_reason_counts: Dict[str, int] = {}
    difficulty_tolerance = float(cfg.get("difficulty_tolerance") or DEFAULT_SEARCH_CONFIG["difficulty_tolerance"])
    judge_sem = asyncio.Semaphore(max(1, int(cfg.get("max_concurrent_judge") or 3)))

    def _bump_reject_reasons(reasons: List[str]) -> None:
        for reason in reasons:
            key = str(reason or "").strip()
            if not key:
                continue
            reject_reason_counts[key] = int(reject_reason_counts.get(key) or 0) + 1

    async def _solve_with_consensus(stem_text: str, solve_options: dict) -> dict:
        async def _run_solve() -> dict:
            try:
                result = await solve_draft(
                    stem_text,
                    solve_options,
                    stream_reasoning=stream_reasoning,
                    on_reasoning_event=on_reasoning_event,
                )
            except RuntimeError as exc:
                result = {
                    "match": False,
                    "final_answer": "",
                    "issues": [f"solver_exception:{str(exc)}"],
                    "summary": "",
                }
            except Exception as exc:
                logger.warning("question_library_solve_draft_unexpected_failed", exc_info=True)
                result = {
                    "match": False,
                    "final_answer": "",
                    "issues": [f"solver_exception:{str(exc)}"],
                    "summary": "",
                }
            return result if isinstance(result, dict) else {}

        outcomes = await asyncio.gather(*[_run_solve() for _ in range(solver_consensus_n)])

        true_votes = sum(1 for item in outcomes if bool(item.get("match")))
        target_match = true_votes * 2 >= len(outcomes) + 1

        combined_issues: List[str] = []
        best_result: dict = {}
        for item in outcomes:
            if not best_result and bool(item.get("match")) == target_match:
                best_result = dict(item)
            raw_issues = item.get("issues")
            if isinstance(raw_issues, list):
                for issue in raw_issues:
                    txt = str(issue or "").strip()
                    if txt:
                        combined_issues.append(txt)
        if not best_result and outcomes:
            best_result = dict(outcomes[0])

        return {
            "match": target_match,
            "final_answer": str(best_result.get("final_answer") or "").strip(),
            "issues": _clip_unique(combined_issues, 8),
            "summary": str(best_result.get("summary") or "").strip(),
            "match_votes": true_votes,
            "consensus_n": len(outcomes),
            "consistency_score": (round(true_votes / len(outcomes), 3) if outcomes else 0.0),
        }

    async def _evaluate_candidate(cand: dict) -> dict:
        async with judge_sem:
            if not isinstance(cand, dict):
                return {"accepted": False, "skip": True, "reasons": []}
            stem = str(cand.get("stem") or "").strip()
            ans = str(cand.get("answer") or "").strip()
            ana = str(cand.get("analysis") or "").strip()
            if not stem or not ans or not ana:
                return {"accepted": False, "skip": True, "reasons": []}

            spec_id = str(cand.get("spec_id") or "").strip()
            spec = next((s for s in specs if isinstance(s, dict) and str(s.get("spec_id") or "").strip() == spec_id), {})
            if not isinstance(spec, dict):
                spec = {}

            attempt = 0
            current = dict(cand)
            local_repairs = 0
            while True:
                solved_result, amb_result = await asyncio.gather(
                    _solve_with_consensus(
                        str(current.get("stem") or ""),
                        {"subject": str(spec.get("subject") or ""), "proposed_answer": str(current.get("answer") or "")},
                    ),
                    check_ambiguity(
                        current,
                        stream_reasoning=stream_reasoning,
                        on_reasoning_event=on_reasoning_event,
                    ),
                    return_exceptions=True,
                )
                if isinstance(solved_result, Exception):
                    solved = {"match": False, "final_answer": "", "issues": [f"solver_exception:{str(solved_result)}"], "summary": ""}
                else:
                    solved = dict(solved_result or {})
                if isinstance(amb_result, Exception):
                    amb = {"ambiguous": True, "issues": [f"ambiguity_exception:{str(amb_result)}"], "summary": ""}
                else:
                    amb = dict(amb_result or {})

                judge_result = await judge_draft(
                    current,
                    spec,
                    source_pack=source_pack,
                    stream_reasoning=stream_reasoning,
                    on_reasoning_event=on_reasoning_event,
                )
                judge = dict(judge_result or {})
                ambiguous_issues = [str(x or "").strip() for x in (amb.get("issues") or []) if str(x or "").strip()][:6]

                issues = list(judge.get("issues") or []) if isinstance(judge.get("issues"), list) else []
                judge_pass = bool(judge.get("pass"))
                overall = max(0, int(judge.get("overall_score") or 0))
                penalty_total = 0
                if not bool(solved.get("match")):
                    penalty_total += answer_mismatch_penalty
                    issues.append("answer_mismatch")
                    solver_issues = solved.get("issues")
                    if isinstance(solver_issues, list):
                        issues.extend([f"solver:{str(x or '').strip()}" for x in solver_issues if str(x or "").strip()])
                if bool(amb.get("ambiguous")):
                    penalty_total += ambiguity_penalty_score
                    issues.extend([f"ambiguous:{x}" for x in ambiguous_issues])
                difficulty_penalty = _difficulty_mismatch_penalty(
                    str(difficulty or "").strip(),
                    str(judge.get("difficulty_estimate") or "").strip(),
                    difficulty_tolerance,
                )
                if difficulty_penalty > 0:
                    penalty_total += difficulty_penalty
                    issues.append("difficulty_mismatch")
                if penalty_total > 0:
                    overall = max(0, overall - penalty_total)
                if overall < judge_floor:
                    issues.append("judge_below_floor")

                normalized_reasons = _clip_unique([str(x or "").strip() for x in issues if str(x or "").strip()], 10)
                keep = dict(current)
                keep["judge"] = dict(judge)
                keep["judge"]["overall_score"] = overall
                keep["judge"]["issues"] = normalized_reasons
                keep["judge"]["penalty_total"] = penalty_total
                keep["judge"]["solver_match"] = bool(solved.get("match"))
                keep["judge"]["solver_final_answer"] = str(solved.get("final_answer") or "").strip()
                keep["judge"]["solver_issues"] = list(solved.get("issues") or []) if isinstance(solved.get("issues"), list) else []
                keep["judge"]["solver_votes"] = int(solved.get("match_votes") or 0)
                keep["judge"]["solver_consensus_n"] = int(solved.get("consensus_n") or 0)
                consistency_score = float(solved.get("consistency_score") or 0.0)
                keep["judge"]["consistency_score"] = consistency_score
                keep["consistency_score"] = consistency_score
                keep["judge"]["ambiguity"] = bool(amb.get("ambiguous"))
                keep["judge"]["ambiguity_issues"] = ambiguous_issues

                if (judge_require_pass_flag and not judge_pass) or overall < judge_floor:
                    passable = False
                else:
                    passable = True

                if passable:
                    return {
                        "accepted": True,
                        "candidate": keep,
                        "score": overall,
                        "reasons": [],
                        "repairs_attempted": local_repairs,
                        "sample": _summarize_candidate_sample(current),
                    }

                has_answer_mismatch = any(reason == "answer_mismatch" for reason in normalized_reasons)
                has_ambiguity = any(reason.startswith("ambiguous:") for reason in normalized_reasons)
                has_difficulty_mismatch = any(reason == "difficulty_mismatch" for reason in normalized_reasons)
                close_to_floor = overall >= repair_min_score and overall < judge_floor and (judge_floor - overall) <= repair_band
                can_repair = (
                    attempt < max_repairs
                    and overall >= repair_min_score
                    and not has_difficulty_mismatch
                    and (has_answer_mismatch or has_ambiguity or close_to_floor)
                )

                if not can_repair:
                    return {
                        "accepted": False,
                        "candidate": dict(current),
                        "score": overall,
                        "reasons": normalized_reasons,
                        "repairs_attempted": local_repairs,
                        "sample": {
                            **_summarize_candidate_sample(current),
                            "judge_summary": str(judge.get("summary") or "").strip(),
                            "judge_issues": normalized_reasons[:6],
                            "ambiguity_issues": ambiguous_issues,
                        },
                    }

                current = await refine_draft(
                    current,
                    judge,
                    stream_reasoning=stream_reasoning,
                    on_reasoning_event=on_reasoning_event,
                )
                local_repairs += 1
                attempt += 1

    judge_tasks = [asyncio.create_task(_evaluate_candidate(cand)) for cand in raw_candidates if isinstance(cand, dict)]
    for future in asyncio.as_completed(judge_tasks):
        result = await future
        if result.get("skip"):
            continue
        judged_total += 1
        repairs_attempted += int(result.get("repairs_attempted") or 0)
        if bool(result.get("accepted")) and isinstance(result.get("candidate"), dict):
            keep = dict(result.get("candidate") or {})
            accepted.append(keep)
            await _emit_callback(on_candidate_accepted, keep)
        else:
            _bump_reject_reasons([str(x or "").strip() for x in (result.get("reasons") or []) if str(x or "").strip()])

        await _emit_stage_event(
            on_stage_event,
            phase="judge",
            label="判题筛选",
            progress=min(90.0, 80.0 + (judged_total / max(1, len(raw_candidates))) * 10.0),
            stats={
                "evaluated": judged_total,
                "accepted": len(accepted),
                "rejected": max(0, judged_total - len(accepted)),
                "pass_rate": round(len(accepted) / max(1, judged_total), 3),
                "repairs_attempted": repairs_attempted,
                "reject_reason_counts": dict(reject_reason_counts),
                "latest_score": int(result.get("score") or 0),
                "latest_consistency_score": (
                    float((result.get("candidate") or {}).get("consistency_score") or 0.0)
                    if isinstance(result.get("candidate"), dict)
                    else 0.0
                ),
            },
            sample=result.get("sample") if isinstance(result.get("sample"), dict) else None,
        )
        await _emit_callback(
            on_generation_snapshot,
            {
                "phase": "judge",
                "raw_candidates": [dict(item) for item in raw_candidates],
                "accepted": [dict(item) for item in accepted],
                "stats": {
                    "evaluated": judged_total,
                    "accepted": len(accepted),
                    "rejected": max(0, judged_total - len(accepted)),
                },
            },
        )

    if not accepted:
        return []

    # Rank by judge overall_score desc (fallback to spec score when missing).
    accepted.sort(
        key=lambda x: int(
            (((x.get("judge") or {}) if isinstance(x.get("judge"), dict) else {}).get("overall_score") or 0)
        ),
        reverse=True,
    )

    finals = select_final(accepted, count=count)
    await _emit_stage_event(
        on_stage_event,
        phase="final_selection",
        label="终选入围",
        progress=92.0,
        stats={
            "accepted_pool": len(accepted),
            "final_count": len(finals),
            "top_scores": [
                int((((item.get("judge") or {}) if isinstance(item.get("judge"), dict) else {}).get("overall_score") or 0))
                for item in finals[:4]
            ],
        },
        sample=_summarize_candidate_sample(finals[0]) if finals else None,
    )
    return finals
