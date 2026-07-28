from __future__ import annotations

import copy
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.generation.study_materials.codex_stages import StageResultError, run_codex_stage
from backend.generation.study_materials.quality_gate import (
    PRESET_PROFILES,
    WORKFLOW_VERSION,
    acceptance_record_is_current,
    build_acceptance_record,
    evaluate_acceptance,
    evaluate_research,
    normalize_preset,
)
from backend.generation.study_materials.tool_executor import ResearchToolOutage, StudyMaterialsToolExecutor

PLAN = "plan"
RESEARCH = "research"
DRAFT = "draft"
REVIEW = "review"
REVISE = "revise"
ACCEPT = "accept"
COMPLETED = "completed"

CodexStageRunner = Callable[..., Awaitable[Dict[str, Any]]]
EventSink = Callable[[Dict[str, Any]], Awaitable[None]]
CheckpointSink = Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[None]]


class WorkflowFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        stage: str,
        issues: Optional[list[str]] = None,
        recoverable: bool = True,
    ) -> None:
        self.code = str(code or "study_materials_workflow_failed")
        self.stage = str(stage or "")
        self.issues = [str(item) for item in (issues or []) if str(item).strip()]
        self.recoverable = bool(recoverable)
        super().__init__(f"{self.code}: {self.stage}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "stage": self.stage,
            "issues": list(self.issues),
            "recoverable": self.recoverable,
        }


async def _noop_event(_event: Dict[str, Any]) -> None:
    return None


async def _noop_checkpoint(_state: Dict[str, Any], _resume: Dict[str, Any]) -> None:
    return None


class StudyMaterialsWorkflow:
    def __init__(
        self,
        *,
        task_id: str,
        user_id: str,
        topic: str,
        subject: str,
        preset: str,
        requirements: str = "",
        options: Optional[Dict[str, Any]] = None,
        resume_working_memory: Optional[Dict[str, Any]] = None,
        stage_runner: Optional[CodexStageRunner] = None,
        tool_executor: Optional[Any] = None,
        event_sink: Optional[EventSink] = None,
        checkpoint_sink: Optional[CheckpointSink] = None,
    ) -> None:
        self.task_id = str(task_id or "").strip()
        self.user_id = str(user_id or "anonymous").strip() or "anonymous"
        self.topic = str(topic or "").strip()
        self.subject = str(subject or "").strip()
        self.preset = normalize_preset(preset)
        self.requirements = str(requirements or "").strip()
        self.options = dict(options or {})
        self.options["preset"] = self.preset
        self.options["requirements"] = self.requirements
        self.stage_runner = stage_runner or run_codex_stage
        self.event_sink = event_sink or _noop_event
        self.checkpoint_sink = checkpoint_sink or _noop_checkpoint
        self.resume_working_memory = dict(resume_working_memory or {})

        restored = self.resume_working_memory.get("study_materials_workflow")
        if isinstance(restored, dict) and int(restored.get("version") or 0) == WORKFLOW_VERSION:
            self.state = copy.deepcopy(restored)
            self.state["preset"] = self.preset
        else:
            self.state: Dict[str, Any] = {
                "version": WORKFLOW_VERSION,
                "stage": PLAN,
                "last_successful_stage": "",
                "preset": self.preset,
                "plan": {},
                "research": {},
                "markdown": str(self.resume_working_memory.get("markdown") or ""),
                "coverage_map": {},
                "review": {},
                "quality_report": {},
                "acceptance": {},
                "revision_attempts": 0,
                "research_attempts": 0,
                "research_retry_points": [],
                "last_failure": {},
            }

        # B8: deepen_research 续作把检索广度提升到 research profile（state preset），
        # 但既有内容的验收仍按原始 preset（options["acceptance_preset"]）评估；
        # 同时开启新的改进周期，修订次数从零计起。
        acceptance_preset = normalize_preset(self.options.get("acceptance_preset")) if str(
            self.options.get("acceptance_preset") or ""
        ).strip() else ""
        self._acceptance_preset_override = acceptance_preset or None
        if str(self.options.get("continue_mode") or "").strip().lower() == "deepen_research":
            self.state["revision_attempts"] = 0

        self.tool_executor = tool_executor or StudyMaterialsToolExecutor(
            topic=self.topic,
            subject=self.subject,
            preset=self.preset,
            user_id=self.user_id,
            options=self.options,
            resume_working_memory=self.resume_working_memory,
        )

    def _acceptance_gate_preset(self) -> str:
        """B8: 验收门实际采用的 preset——deepen 续作用原 preset，否则用 state preset。"""

        return self._acceptance_preset_override or self.preset

    def _resume_snapshot(self) -> Dict[str, Any]:
        tool_memory = getattr(self.tool_executor, "working_memory", {})
        resume = dict(tool_memory) if isinstance(tool_memory, dict) else {}
        resume.update(self.resume_working_memory)
        markdown = str(self.state.get("markdown") or "")
        if markdown:
            resume["markdown"] = markdown
            resume["assemble_study_archive"] = markdown
            resume["generate_study_material"] = {
                "topic": self.topic,
                "subject": self.subject,
                "preset": self.preset,
                "coverage_map": dict(self.state.get("coverage_map") or {}),
            }
        resume["study_options"] = {
            **(dict(resume.get("study_options") or {}) if isinstance(resume.get("study_options"), dict) else {}),
            **self.options,
        }
        step_results = getattr(self.tool_executor, "step_results", None)
        if isinstance(step_results, list):
            resume["step_results"] = [dict(item) for item in step_results if isinstance(item, dict)]
        resume["study_materials_workflow"] = copy.deepcopy(self.state)
        self.resume_working_memory = resume
        return copy.deepcopy(resume)

    async def _checkpoint(self) -> None:
        await self.checkpoint_sink(copy.deepcopy(self.state), self._resume_snapshot())

    async def _set_stage(self, stage: str, *, successful: str = "") -> None:
        if successful:
            self.state["last_successful_stage"] = successful
        self.state["stage"] = stage
        await self.event_sink(
            {
                "type": "workflow_stage",
                "event": "workflow_stage",
                "data": {
                    "stage": stage,
                    "last_successful_stage": self.state.get("last_successful_stage") or "",
                    "revision_attempts": int(self.state.get("revision_attempts") or 0),
                    "research_attempts": int(self.state.get("research_attempts") or 0),
                },
            }
        )
        await self._checkpoint()

    async def _fail(self, failure: WorkflowFailure) -> None:
        self.state["last_failure"] = failure.to_dict()
        self.state["stage"] = failure.stage
        # 先落盘再广播：event_sink 可能在任务取消时抛 CancelledError，
        # 若顺序反过来会丢掉 last_failure 的检查点。
        await self._checkpoint()
        await self.event_sink(
            {
                "type": "recovery_available",
                "event": "recovery_available",
                "data": failure.to_dict(),
            }
        )

    async def _run_codex(self, stage: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await self.stage_runner(
                stage=stage,
                task_id=self.task_id,
                user_id=self.user_id,
                topic=self.topic,
                subject=self.subject,
                preset=self.preset,
                options=self.options,
                payload=payload,
                event_sink=self.event_sink,
            )
        except StageResultError as exc:
            failed_stage = str(exc.stage or stage).strip() or stage
            self.state["last_failure"] = {
                "code": exc.code,
                "stage": failed_stage,
                "detail": exc.detail,
                "recoverable": True,
            }
            self.state["stage"] = failed_stage
            await self._checkpoint()
            raise

    async def run(self) -> Dict[str, Any]:
        profile = PRESET_PROFILES[self.preset]
        # 迭代上限推导：plan/draft/accept 等线性阶段固定约占 8 次；
        # 每个审查/检索重试周期最多再占 3 次阶段跳转（review→revise→review
        # 或 research→(checkpoint)→research），按当前 preset 的周期数放大。
        max_iterations = 8 + 3 * (int(profile["max_review_cycles"]) + int(profile["max_research_cycles"]))
        for _ in range(max_iterations):
            stage = str(self.state.get("stage") or PLAN)
            if stage == PLAN:
                plan = await self._run_codex(
                    PLAN,
                    {"requirements": self.requirements, "prior_state": self.state.get("last_failure") or {}},
                )
                self.state["plan"] = dict(plan)
                self.state["last_failure"] = {}
                await self._set_stage(RESEARCH, successful=PLAN)
                continue

            if stage == RESEARCH:
                retry_points = [
                    str(item or "").strip()
                    for item in (self.state.get("research_retry_points") or [])
                    if str(item or "").strip()
                ]
                try:
                    research = await self.tool_executor.research(
                        plan=dict(self.state.get("plan") or {}),
                        event_sink=self.event_sink,
                        only_point_ids=retry_points or None,
                        attempt=int(self.state.get("research_attempts") or 0),
                    )
                except ResearchToolOutage as outage:
                    failure = WorkflowFailure(
                        "research_tool_outage",
                        stage=RESEARCH,
                        issues=[f"tool_unavailable:{tool}" for tool in outage.tools] or ["tool_unavailable"],
                    )
                    await self._fail(failure)
                    raise failure
                self.state["research"] = dict(research)
                research_report = evaluate_research(state=self.state)
                await self.event_sink(
                    {"type": "quality_report", "event": "quality_report", "data": research_report}
                )
                if not research_report["passed"]:
                    failed_point_ids = [
                        str(point_id)
                        for point_id, detail in (research_report.get("per_knowledge_point") or {}).items()
                        if isinstance(detail, dict) and not detail.get("passed")
                    ]
                    research_attempts = int(self.state.get("research_attempts") or 0)
                    max_research_attempts = int(PRESET_PROFILES[self.preset]["max_research_cycles"])
                    if failed_point_ids and research_attempts < max_research_attempts:
                        research_attempts += 1
                        self.state["research_attempts"] = research_attempts
                        self.state["research_retry_points"] = failed_point_ids
                        await self.event_sink(
                            {
                                "type": "research_retry_required",
                                "event": "research_retry_required",
                                "data": {
                                    "point_ids": list(failed_point_ids),
                                    "attempt": research_attempts,
                                    "remaining_attempts": max_research_attempts - research_attempts,
                                },
                            }
                        )
                        await self._set_stage(RESEARCH)
                        continue
                    failure = WorkflowFailure(
                        "quality_gate_not_met",
                        stage=RESEARCH,
                        issues=list(research_report["failed_checks"]),
                    )
                    await self._fail(failure)
                    raise failure
                self.state["research_retry_points"] = []
                next_stage = REVIEW if self.state.get("markdown") and self.state.get("resume_after_research") == REVIEW else DRAFT
                await self._set_stage(next_stage, successful=RESEARCH)
                continue

            if stage == DRAFT:
                draft = await self._run_codex(
                    DRAFT,
                    {"plan": self.state.get("plan") or {}, "research": self.state.get("research") or {}},
                )
                self.state["markdown"] = str(draft.get("markdown") or "")
                self.state["coverage_map"] = dict(draft.get("coverage_map") or {})
                self.state["review"] = {}
                await self.event_sink(
                    {"type": "text_delta", "event": "text_delta", "data": {"content": self.state["markdown"]}}
                )
                await self._set_stage(REVIEW, successful=DRAFT)
                continue

            if stage == REVIEW:
                if not str(self.state.get("markdown") or "").strip():
                    # 空稿没有可审查内容，直接回 DRAFT 重新生成（防死循环由上面的迭代上限兜底）。
                    await self._set_stage(DRAFT)
                    continue
                review = await self.tool_executor.review(
                    markdown=str(self.state.get("markdown") or ""),
                    event_sink=self.event_sink,
                )
                self.state["review"] = dict(review)
                report = evaluate_acceptance(
                    state=self.state,
                    preset_override=self._acceptance_preset_override,
                )
                self.state["quality_report"] = dict(report)
                await self.event_sink({"type": "quality_report", "event": "quality_report", "data": report})
                await self._checkpoint()
                if report["passed"]:
                    await self._set_stage(ACCEPT, successful=REVIEW)
                    continue

                attempts = int(self.state.get("revision_attempts") or 0)
                max_attempts = int(PRESET_PROFILES[self.preset]["max_review_cycles"])
                if attempts >= max_attempts:
                    issues = list(report.get("failed_checks") or []) + list(review.get("issues") or [])
                    if str(self.state.get("markdown") or "").strip():
                        # 尽力交付：修订次数用尽但已有成稿时降级完成，不落验收记录。
                        await self.event_sink(
                            {
                                "type": "quality_degraded",
                                "event": "quality_degraded",
                                "data": {"issues": issues, "revision_attempts": attempts},
                            }
                        )
                        self.state["acceptance"] = {}
                        await self._set_stage(COMPLETED)
                        return self._degraded_result(issues=issues)
                    failure = WorkflowFailure("quality_gate_not_met", stage=REVIEW, issues=issues)
                    await self._fail(failure)
                    raise failure
                await self.event_sink(
                    {
                        "type": "revision_required",
                        "event": "revision_required",
                        "data": {
                            "issues": list(review.get("issues") or []) + list(report.get("failed_checks") or []),
                            "remaining_attempts": max_attempts - attempts,
                        },
                    }
                )
                await self._set_stage(REVISE, successful=REVIEW)
                continue

            if stage == REVISE:
                review = self.state.get("review") if isinstance(self.state.get("review"), dict) else {}
                report = self.state.get("quality_report") if isinstance(self.state.get("quality_report"), dict) else {}
                revised = await self._run_codex(
                    REVISE,
                    {
                        "markdown": str(self.state.get("markdown") or ""),
                        "issues": list(review.get("issues") or []) + list(report.get("failed_checks") or []),
                        "plan": self.state.get("plan") or {},
                        "research": self.state.get("research") or {},
                    },
                )
                self.state["markdown"] = str(revised.get("markdown") or "")
                self.state["coverage_map"] = dict(revised.get("coverage_map") or {})
                self.state["resolved_issues"] = list(revised.get("resolved_issues") or [])
                self.state["review"] = {}
                self.state["revision_attempts"] = int(self.state.get("revision_attempts") or 0) + 1
                await self.event_sink(
                    {"type": "text_delta", "event": "text_delta", "data": {"content": self.state["markdown"]}}
                )
                await self._set_stage(REVIEW, successful=REVISE)
                continue

            if stage == ACCEPT:
                report = evaluate_acceptance(
                    state=self.state,
                    preset_override=self._acceptance_preset_override,
                )
                self.state["quality_report"] = dict(report)
                if not report["passed"]:
                    if str(self.state.get("markdown") or "").strip():
                        # 与 REVIEW 相同的降级交付：成稿存在但复评未过时不写验收记录。
                        review = self.state.get("review") if isinstance(self.state.get("review"), dict) else {}
                        issues = list(report.get("failed_checks") or []) + list(review.get("issues") or [])
                        await self.event_sink(
                            {
                                "type": "quality_degraded",
                                "event": "quality_degraded",
                                "data": {
                                    "issues": issues,
                                    "revision_attempts": int(self.state.get("revision_attempts") or 0),
                                },
                            }
                        )
                        self.state["acceptance"] = {}
                        await self._set_stage(COMPLETED)
                        return self._degraded_result(issues=issues)
                    failure = WorkflowFailure(
                        "quality_gate_not_met",
                        stage=ACCEPT,
                        issues=list(report.get("failed_checks") or []),
                    )
                    await self._fail(failure)
                    raise failure
                acceptance = build_acceptance_record(
                    report=report,
                    preset=self._acceptance_gate_preset(),
                    options=self.options,
                )
                self.state["acceptance"] = acceptance
                await self._set_stage(COMPLETED, successful=ACCEPT)
                return self._accepted_result()

            if stage == COMPLETED:
                archive = {"acceptance": self.state.get("acceptance") or {}}
                if acceptance_record_is_current(
                    archive=archive,
                    preset=self._acceptance_gate_preset(),
                    markdown=str(self.state.get("markdown") or ""),
                    options=self.options,
                ):
                    return self._accepted_result()
                self.state["stage"] = REVIEW
                continue

            failure = WorkflowFailure("invalid_workflow_stage", stage=stage, recoverable=False)
            await self._fail(failure)
            raise failure

        failure = WorkflowFailure("workflow_iteration_limit", stage=str(self.state.get("stage") or ""))
        await self._fail(failure)
        raise failure

    def _accepted_result(self) -> Dict[str, Any]:
        markdown = str(self.state.get("markdown") or "")
        return {
            "success": True,
            "material": {
                "topic": self.topic,
                "subject": self.subject,
                "markdown": markdown,
                "iteration": int(self.state.get("revision_attempts") or 0) + 1,
                "passed": True,
                "issues": [],
                "error": None,
            },
            "quality_report": copy.deepcopy(self.state.get("quality_report") or {}),
            "review": copy.deepcopy(self.state.get("review") or {}),
            "acceptance": copy.deepcopy(self.state.get("acceptance") or {}),
            "workflow": copy.deepcopy(self.state),
            "resume_working_memory": self._resume_snapshot(),
        }

    def _degraded_result(self, *, issues: List[str]) -> Dict[str, Any]:
        # 与 _accepted_result 同形，但标记 degraded、material.passed=False，
        # 且不带验收记录（归档不得复用降级产物）。
        result = self._accepted_result()
        material = dict(result["material"])
        material["passed"] = False
        material["issues"] = [str(issue) for issue in issues if str(issue or "").strip()]
        result["material"] = material
        result["degraded"] = True
        result["acceptance"] = {}
        return result


async def run_study_materials_workflow(
    *,
    task_id: str,
    user_id: str,
    topic: str,
    subject: str,
    preset: str,
    requirements: str = "",
    options: Optional[Dict[str, Any]] = None,
    resume_working_memory: Optional[Dict[str, Any]] = None,
    event_sink: Optional[EventSink] = None,
    checkpoint_sink: Optional[CheckpointSink] = None,
) -> Dict[str, Any]:
    workflow = StudyMaterialsWorkflow(
        task_id=task_id,
        user_id=user_id,
        topic=topic,
        subject=subject,
        preset=preset,
        requirements=requirements,
        options=options,
        resume_working_memory=resume_working_memory,
        event_sink=event_sink,
        checkpoint_sink=checkpoint_sink,
    )
    return await workflow.run()
