from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from backend.core.logging_utils import get_logger
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
from backend.generation.question_library.curriculum_context import (
    build_curriculum_context,
    enrich_source_pack_with_curriculum,
)
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
    _emit_callback,
    _emit_stage_event,
    _resolve_runtime_search_config,
    _summarize_candidate_sample,
    build_ai_question_id,
)
from backend.generation.question_library.intuition_practice import (
    attach_quick_validation,
    intuition_packet_signature,
    normalize_intuition_practice_config,
    validate_intuition_packet_structure,
)
from backend.generation.question_library.judging import (
    check_ambiguity,
    judge_draft,
    quick_validate_draft,
    refine_draft,
    solve_draft,
)
from backend.generation.question_library.reference_analysis import (
    analyze_reference_questions,
    enrich_source_pack_with_reference,
)
from backend.generation.question_library.reference_crawl import collect_reference_questions
from backend.generation.question_library.selection import select_final
from backend.generation.question_library.source_pack import build_source_pack
from backend.generation.question_library.spec_scoring import score_spec
from backend.llm.client import is_llm_configured

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
    "quick_validate_draft",
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
    original_source_pack = dict(source_pack)
    practice_config = normalize_intuition_practice_config(original_source_pack.get("intuition_practice"))
    source_pack = {**original_source_pack, "intuition_practice": practice_config}
    if not source_pack.get("skills") and not source_pack.get("forbidden_patterns"):
        try:
            rebuilt_source_pack = await build_source_pack(
                str(source_pack.get("study_markdown") or ""),
                str(source_pack.get("subject") or ""),
                str(source_pack.get("topic") or ""),
                stream_reasoning=stream_reasoning,
                on_reasoning_event=on_reasoning_event,
            )
            # Distillation must not erase request-owned generation constraints.
            source_pack = {
                **original_source_pack,
                **(rebuilt_source_pack if isinstance(rebuilt_source_pack, dict) else {}),
                "intuition_practice": practice_config,
            }
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
                label="直觉原子设计",
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
                label="直觉原子设计",
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
        label="练习包设计",
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

    realize_results = await asyncio.gather(*[_realize_spec(spec) for spec in specs], return_exceptions=True) if specs else []
    for spec, result in zip(specs, realize_results):
        if isinstance(result, BaseException):
            drafts: list[dict] = []
            error: Optional[BaseException] = result
        else:
            drafts, error = result
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
        label="练习包生成",
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

    # Stage: one lightweight self-practice validation call + at most one repair.
    accepted: List[dict] = []
    max_repairs = min(1, max(0, int(cfg.get("max_repair_rounds") or 0)))
    judged_total = 0
    repairs_attempted = 0
    reject_reason_counts: Dict[str, int] = {}
    judge_sem = asyncio.Semaphore(max(1, int(cfg.get("max_concurrent_judge") or 3)))

    def _bump_reject_reasons(reasons: List[str]) -> None:
        for reason in reasons:
            key = str(reason or "").strip()
            if not key:
                continue
            reject_reason_counts[key] = int(reject_reason_counts.get(key) or 0) + 1

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
                packet_issues = validate_intuition_packet_structure(
                    current.get("intuition_packet"),
                    packet_size=int(source_pack["intuition_practice"]["packet_size"]),
                )
                if packet_issues:
                    validation_result: dict = {
                        "pass": False,
                        "scope_ok": True,
                        "answer_correct": True,
                        "answer_analysis_consistent": True,
                        "conditions_sufficient": False,
                        "unambiguous": False,
                        "transfer_valid": False,
                        "intuition_aligned": False,
                        "structural_depth": False,
                        "request_aligned": False,
                        "issues": packet_issues,
                        "summary": "直觉练习包结构不完整。",
                        "overall_score": 0,
                    }
                else:
                    try:
                        validation_result = await quick_validate_draft(
                            current,
                            spec,
                            source_pack=source_pack,
                            stream_reasoning=stream_reasoning,
                            on_reasoning_event=on_reasoning_event,
                        )
                    except Exception as exc:
                        logger.warning("question_library_quick_validation_failed", exc_info=True)
                        validation_result = {
                            "pass": False,
                            "scope_ok": False,
                            "answer_correct": False,
                            "answer_analysis_consistent": False,
                            "conditions_sufficient": False,
                            "unambiguous": False,
                            "transfer_valid": False,
                            "intuition_aligned": False,
                            "structural_depth": False,
                            "request_aligned": False,
                            "issues": [f"quick_validation_exception:{str(exc)}"],
                            "summary": "",
                            "overall_score": 0,
                        }
                judge = dict(validation_result or {})
                solved = {
                    "match": bool(judge.get("answer_correct"))
                    and bool(judge.get("answer_analysis_consistent")),
                    "final_answer": str(current.get("answer") or "").strip(),
                    "issues": [
                        str(x or "").strip()
                        for x in (judge.get("issues") or [])
                        if str(x or "").strip()
                        and ("answer" in str(x).lower() or "答案" in str(x))
                    ],
                    "match_votes": 1 if bool(judge.get("answer_correct")) else 0,
                    "consensus_n": 1,
                    "consistency_score": 1.0 if bool(judge.get("pass")) else 0.0,
                }
                amb = {
                    "ambiguous": not (
                        bool(judge.get("conditions_sufficient")) and bool(judge.get("unambiguous"))
                    ),
                    "issues": [
                        str(x or "").strip()
                        for x in (judge.get("issues") or [])
                        if str(x or "").strip()
                        and any(token in str(x).lower() for token in ("ambigu", "condition", "歧义", "条件"))
                    ],
                    "summary": str(judge.get("summary") or "").strip(),
                }
                ambiguous_issues = [str(x or "").strip() for x in (amb.get("issues") or []) if str(x or "").strip()][:6]

                issues = list(judge.get("issues") or []) if isinstance(judge.get("issues"), list) else []
                judge_pass = bool(judge.get("pass"))
                overall = 100 if judge_pass else 0
                penalty_total = 0
                if not bool(solved.get("match")):
                    issues.append("answer_mismatch")
                    solver_issues = solved.get("issues")
                    if isinstance(solver_issues, list):
                        issues.extend([f"solver:{str(x or '').strip()}" for x in solver_issues if str(x or "").strip()])
                if bool(amb.get("ambiguous")):
                    issues.extend([f"ambiguous:{x}" for x in ambiguous_issues])
                if not judge_pass:
                    issues.append("quick_validation_failed")

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
                keep["quick_validation"] = dict(judge)
                keep["intuition_packet"] = attach_quick_validation(
                    current.get("intuition_packet") if isinstance(current.get("intuition_packet"), dict) else {},
                    judge,
                    repaired=local_repairs > 0,
                )
                check_dimensions = [
                    ("课内范围", "scope_ok"),
                    ("答案正确", "answer_correct"),
                    ("答案解析一致", "answer_analysis_consistent"),
                    ("条件充分", "conditions_sufficient"),
                    ("无致命歧义", "unambiguous"),
                    ("迁移有效", "transfer_valid"),
                    ("直觉一致", "intuition_aligned"),
                    ("结构深度", "structural_depth"),
                    ("请求契约", "request_aligned"),
                ]
                keep["review"] = {
                    "verdict": "可练习" if judge_pass else "需修复",
                    "overall_score": overall,
                    "dimensions": [
                        {
                            "name": name,
                            "score": 10 if bool(judge.get(key)) else 0,
                            "comment": "通过" if bool(judge.get(key)) else "未通过",
                        }
                        for name, key in check_dimensions
                    ],
                    "highlights": [],
                    "issues": normalized_reasons,
                    "summary": str(judge.get("summary") or "").strip(),
                    "model": "quick-validation",
                }

                passable = judge_pass

                if passable:
                    return {
                        "accepted": True,
                        "candidate": keep,
                        "score": overall,
                        "reasons": [],
                        "repairs_attempted": local_repairs,
                        "sample": _summarize_candidate_sample(current),
                    }

                can_repair = attempt < max_repairs and bool(normalized_reasons)

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
                    spec=spec,
                    source_pack=source_pack,
                    stream_reasoning=stream_reasoning,
                    on_reasoning_event=on_reasoning_event,
                )
                local_repairs += 1
                attempt += 1

    accepted_signatures: set[str] = set()
    judge_tasks = [asyncio.create_task(_evaluate_candidate(cand)) for cand in raw_candidates if isinstance(cand, dict)]
    for future in asyncio.as_completed(judge_tasks):
        result = await future
        if result.get("skip"):
            continue
        judged_total += 1
        repairs_attempted += int(result.get("repairs_attempted") or 0)
        if bool(result.get("accepted")) and isinstance(result.get("candidate"), dict):
            keep = dict(result.get("candidate") or {})
            signature = intuition_packet_signature(keep.get("intuition_packet"))
            if signature and signature in accepted_signatures:
                _bump_reject_reasons(["duplicate_intuition_packet"])
            else:
                if signature:
                    accepted_signatures.add(signature)
                accepted.append(keep)
                await _emit_callback(on_candidate_accepted, keep)
        else:
            _bump_reject_reasons([str(x or "").strip() for x in (result.get("reasons") or []) if str(x or "").strip()])

        await _emit_stage_event(
            on_stage_event,
            phase="judge",
            label="快速校验",
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
        label="练习包去重",
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
