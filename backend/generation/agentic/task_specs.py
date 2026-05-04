from __future__ import annotations

import time
from typing import Any, Dict, Optional

from backend.generation.agentic.study_materials import build_study_materials_agent_spec
from backend.generation.agentic.types import (
    AgentBudget,
    AgentRoleSpec,
    AgentRunSpec,
    AgentSearchPolicy,
    AgentToolPolicy,
)


def _text(value: Any, default: str = "") -> str:
    raw = str(value if value is not None else "").strip()
    return raw or default


def _int(value: Any, *, default: int, min_v: int = 1, max_v: int = 10_000) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = int(default)
    return max(min_v, min(max_v, n))


def _metadata(task_type: str, *, weight: str = "medium", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = {
        "native_agentic": True,
        "task_type": _text(task_type, "unknown"),
        "weight": _text(weight, "medium"),
    }
    if isinstance(extra, dict):
        data.update(extra)
    return data


def build_agent_run_spec_for_task(
    *,
    task_type: str,
    request: Dict[str, Any] | None,
    resume_state: Dict[str, Any] | None = None,
) -> Optional[AgentRunSpec]:
    """Build the canonical native-agentic contract for a medium/heavy AI task."""

    req = dict(request or {})
    t = _text(task_type).replace(".", "_").replace("-", "_")
    resume = dict(resume_state or {})

    if t == "study_materials":
        spec = build_study_materials_agent_spec(
            query=_text(req.get("query") or req.get("topic")),
            subject=_text(req.get("subject")),
            options=req.get("options") if isinstance(req.get("options"), dict) else req,
            resume_state=resume,
        )
        return AgentRunSpec(
            domain=spec.domain,
            goal=spec.goal,
            subject=spec.subject,
            user_requirements=spec.user_requirements,
            input_payload=spec.input_payload,
            roles=spec.roles,
            tool_policy=spec.tool_policy,
            search_policy=spec.search_policy,
            budget=spec.budget,
            output_contract=spec.output_contract,
            resume_state=spec.resume_state,
            metadata={**spec.metadata, **_metadata(t, weight="heavy")},
        )

    if t == "deepthink":
        subject = _text(req.get("subject"), "高中数学")
        question = _text(req.get("question"))
        return AgentRunSpec(
            domain="deepthink",
            goal=f"使用多步推理求解题目：{question[:120] or subject}",
            subject=subject,
            input_payload={"question": question, "image_url": _text(req.get("image_url") or req.get("imageUrl"))},
            roles=[
                AgentRoleSpec(name="generator", prompt_id="deepthink.generator.v1"),
                AgentRoleSpec(name="evaluator", prompt_id="deepthink.evaluator.v1"),
                AgentRoleSpec(name="synthesizer", prompt_id="deepthink.synthesizer.v1"),
            ],
            tool_policy=AgentToolPolicy(
                allowed_tools=[
                    "propose_reasoning_step",
                    "evaluate_reasoning_step",
                    "select_best_reasoning_path",
                    "synthesize_solution",
                ],
                allow_parallel=True,
                max_consecutive_failures=2,
            ),
            budget=AgentBudget(max_llm_calls=28, max_tool_calls=48, max_iterations=18, max_runtime_s=900),
            output_contract={"kind": "solution_markdown", "stream": ["reasoning_tree", "answer_delta"]},
            resume_state=resume,
            metadata=_metadata(t, weight="heavy"),
        )

    if t == "lesson_plan":
        subject = _text(req.get("subject"))
        grade = _text(req.get("grade"))
        topic = _text(req.get("topic"))
        return AgentRunSpec(
            domain="lesson_plan",
            goal=f"生成可导出教案：{subject} {grade} {topic}".strip(),
            subject=subject,
            user_requirements=_text(req.get("additional_requirements") or req.get("requirements")),
            input_payload=dict(req),
            roles=[
                AgentRoleSpec(name="planner", prompt_id="lesson_plan.activity_planner.v1"),
                AgentRoleSpec(name="researcher", prompt_id="lesson_plan.kp_facts.v1"),
                AgentRoleSpec(name="writer", prompt_id="lesson_plan.writer.v1"),
                AgentRoleSpec(name="exporter", prompt_id="lesson_plan.latex_convert.v1", required=False),
                AgentRoleSpec(name="repairer", prompt_id="lesson_plan.latex_repair.v1", required=False),
            ],
            tool_policy=AgentToolPolicy(
                allowed_tools=[
                    "split_knowledge_points",
                    "review_knowledge_points",
                    "research_knowledge_point",
                    "generate_lesson_plan",
                    "assemble_study_archive",
                    "export_study_markdown",
                    "convert_markdown_to_latex",
                    "refine_latex",
                    "compile_latex_to_pdf",
                ],
                allow_parallel=True,
                max_consecutive_failures=3,
            ),
            budget=AgentBudget(max_llm_calls=24, max_tool_calls=42, max_iterations=18, max_runtime_s=1200),
            output_contract={"kind": "lesson_plan", "formats": ["markdown", "pdf"]},
            resume_state=resume,
            metadata=_metadata(t, weight="heavy"),
        )

    if t in {"paper_compose", "paper_generate_full"}:
        subject = _text(req.get("subject"))
        topic = _text(req.get("topic") or req.get("paperName") or req.get("paper_name"))
        is_full = t == "paper_generate_full"
        return AgentRunSpec(
            domain="paper_compose",
            goal=("一键生成完整试卷" if is_full else "按蓝图组装试卷") + (f"：{subject} {topic}" if subject or topic else ""),
            subject=subject,
            user_requirements=_text(req.get("requirements") or req.get("prompt") or req.get("description")),
            input_payload=dict(req),
            roles=[
                AgentRoleSpec(name="planner", prompt_id="chat.paper_compose.system.v1"),
                AgentRoleSpec(name="searcher", prompt_id="chat.paper_compose.system.v1"),
                AgentRoleSpec(name="composer", prompt_id="chat.paper_compose.system.v1"),
                AgentRoleSpec(name="reviewer", prompt_id="question.judge.quality.v1", required=False),
            ],
            tool_policy=AgentToolPolicy(
                allowed_tools=[
                    "get_available_filters",
                    "search_questions",
                    "batch_get_question_details",
                    "compose_paper_blueprint",
                    "review_question_match",
                    "create_paper",
                    "analyze_paper",
                ],
                allow_parallel=True,
                max_consecutive_failures=3,
            ),
            search_policy=AgentSearchPolicy(providers=["local_question_library", "crawler"]),
            budget=AgentBudget(
                max_llm_calls=20 if is_full else 12,
                max_tool_calls=50 if is_full else 32,
                max_iterations=18 if is_full else 12,
                max_runtime_s=1200 if is_full else 900,
            ),
            output_contract={"kind": "paper", "requires_confirmation": not is_full},
            resume_state=resume,
            metadata=_metadata(t, weight="heavy" if is_full else "medium"),
        )

    if t == "knowledge_video":
        subject = _text(req.get("subject"))
        topic = _text(req.get("topic") or req.get("query"))
        return AgentRunSpec(
            domain="knowledge_video",
            goal=f"生成可渲染知识视频：{topic or subject}",
            subject=subject,
            user_requirements=_text(req.get("requirements") or req.get("style")),
            input_payload=dict(req),
            roles=[
                AgentRoleSpec(name="planner", prompt_id="knowledge_video.manim_package.v1"),
                AgentRoleSpec(name="scriptwriter", prompt_id="knowledge_video.manim_package.v1"),
                AgentRoleSpec(name="safety_reviewer", prompt_id="knowledge_video.manim_package.v1"),
                AgentRoleSpec(name="renderer", prompt_id="knowledge_video.manim_package.v1"),
            ],
            tool_policy=AgentToolPolicy(
                allowed_tools=[
                    "hydrate_study_archive",
                    "generate_manim_package",
                    "validate_manim_code",
                    "render_manim_docker",
                    "repair_manim_package",
                    "publish_generated_video",
                ],
                allow_parallel=False,
                max_consecutive_failures=2,
            ),
            budget=AgentBudget(max_llm_calls=8, max_tool_calls=16, max_iterations=8, max_runtime_s=1800),
            output_contract={"kind": "knowledge_video", "formats": ["mp4", "srt", "json", "py"]},
            resume_state=resume,
            metadata=_metadata(t, weight="heavy", extra={"sandbox": "docker-only"}),
        )

    if t == "question_library_generate":
        subject = _text(req.get("subject"))
        topic = _text(req.get("topic"))
        return AgentRunSpec(
            domain="question_generation",
            goal=f"生成待审核原创题：{subject} {topic}".strip(),
            subject=subject,
            user_requirements=_text(req.get("requirements") or req.get("extra_requirements")),
            input_payload=dict(req),
            roles=[
                AgentRoleSpec(name="source_curator", prompt_id="question.brainstorm.v1"),
                AgentRoleSpec(name="reference_researcher", prompt_id="question.brainstorm.v1", required=False),
                AgentRoleSpec(name="brainstormer", prompt_id="question.brainstorm.v1"),
                AgentRoleSpec(name="drafter", prompt_id="question.draft.realize.v1"),
                AgentRoleSpec(name="judge", prompt_id="question.judge.quality.v1"),
                AgentRoleSpec(name="repairer", prompt_id="question.repair.minimal.v1", required=False),
            ],
            tool_policy=AgentToolPolicy(
                allowed_tools=[
                    "build_source_pack",
                    "crawl_reference_questions",
                    "analyze_reference_questions",
                    "brainstorm_question_seeds",
                    "search_question_specs",
                    "realize_question_drafts",
                    "generate_question_diagrams",
                    "solve_question_independently",
                    "judge_question_ambiguity",
                    "judge_question_quality",
                    "select_final_questions",
                    "save_question_preview",
                ],
                allow_parallel=True,
                max_consecutive_failures=3,
            ),
            search_policy=AgentSearchPolicy(providers=["local_question_library", "crawler", "tavily"]),
            budget=AgentBudget(
                max_llm_calls=max(12, _int(req.get("count"), default=3, min_v=1, max_v=50) * 8),
                max_tool_calls=max(24, _int(req.get("count"), default=3, min_v=1, max_v=50) * 14),
                max_iterations=20,
                max_runtime_s=1800,
            ),
            output_contract={"kind": "question_preview_session", "review_required": True},
            resume_state=resume,
            metadata=_metadata(t, weight="heavy"),
        )

    if t == "question_library_score":
        subject = _text(req.get("subject"))
        return AgentRunSpec(
            domain="question_generation",
            goal=f"批量审题评分：{subject}",
            subject=subject,
            input_payload=dict(req),
            roles=[
                AgentRoleSpec(name="loader", prompt_id="question.evaluate.external.v1"),
                AgentRoleSpec(name="reviewer", prompt_id="question.evaluate.external.v1"),
                AgentRoleSpec(name="moderator", prompt_id="question.judge.quality.v1"),
            ],
            tool_policy=AgentToolPolicy(
                allowed_tools=["load_question_batch", "score_stem_with_llm", "apply_score_and_hide", "save_score_report"],
                allow_parallel=True,
                max_consecutive_failures=5,
            ),
            budget=AgentBudget(
                max_llm_calls=_int(req.get("limit"), default=50, min_v=1, max_v=500),
                max_tool_calls=_int(req.get("limit"), default=50, min_v=1, max_v=500) + 4,
                max_iterations=8,
                max_runtime_s=1200,
            ),
            output_contract={"kind": "question_score_report"},
            resume_state=resume,
            metadata=_metadata(t, weight="medium"),
        )

    if t == "question_evaluate":
        subject = _text(req.get("subject"))
        count = len(req.get("questions") or []) if isinstance(req.get("questions"), list) else 0
        return AgentRunSpec(
            domain="question_evaluate",
            goal=f"批量鉴别题目质量：{subject}，共 {count} 题".strip(),
            subject=subject,
            user_requirements=_text(req.get("requirements")),
            input_payload=dict(req),
            roles=[
                AgentRoleSpec(name="loader", prompt_id="question.evaluate.external.v1"),
                AgentRoleSpec(name="rubric_reviewer", prompt_id="question.evaluate.external.v1"),
                AgentRoleSpec(name="ranker", prompt_id="question.judge.quality.v1", required=False),
            ],
            tool_policy=AgentToolPolicy(
                allowed_tools=[
                    "load_evaluation_batch",
                    "evaluate_question_quality",
                    "normalize_quality_rubric",
                    "rank_evaluation_results",
                ],
                allow_parallel=True,
                max_consecutive_failures=4,
            ),
            budget=AgentBudget(
                max_llm_calls=max(1, min(50, count or 1)),
                max_tool_calls=max(4, min(50, count or 1) + 4),
                max_iterations=8,
                max_runtime_s=1200,
            ),
            output_contract={"kind": "question_evaluation_report", "ordered_by": "overall_score_desc"},
            resume_state=resume,
            metadata=_metadata(t, weight="medium"),
        )

    return None


def agentic_task_meta(spec: Optional[AgentRunSpec], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = dict(extra or {})
    if spec is not None:
        meta["native_agentic"] = True
        meta["agent_run_spec"] = spec.to_dict()
    return meta


def build_agentic_starter_event(
    *,
    spec: AgentRunSpec,
    title: str,
    tool_name: str,
) -> Dict[str, Any]:
    return {
        "type": "step",
        "step": {
            "id": "agent_run_started",
            "title": _text(title, "Agentic 任务开始"),
            "status": "running",
            "startTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "toolName": _text(tool_name, spec.domain),
            "input": {"domain": spec.domain, "goal": spec.goal, "subject": spec.subject},
        },
        "data": {
            "native_agentic": True,
            "agent_run_spec": spec.to_dict(),
        },
    }
