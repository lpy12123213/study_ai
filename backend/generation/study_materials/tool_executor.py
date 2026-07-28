from __future__ import annotations

import asyncio
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.agent.context import ContextManager
from backend.agent.executor import Executor
from backend.agent.types import CompressedContext, PlanStep, StepResult, UserProfile, agent_event
from backend.core.settings import env_int
from backend.generation.study_materials.quality_gate import (
    PRESET_PROFILES,
    draft_hash,
    normalize_evidence,
    normalize_preset,
)

EventSink = Callable[[Dict[str, Any]], Awaitable[None]]


class ResearchToolOutage(RuntimeError):
    """连续工具失败达到上限，说明检索链路整体不可用（而非单个知识点证据不足）。"""

    def __init__(self, tools: List[str]) -> None:
        self.tools = [str(tool or "").strip() for tool in tools if str(tool or "").strip()]
        detail = ",".join(self.tools) or "unknown"
        super().__init__(f"research_tool_outage: {detail}")


class StudyMaterialsToolExecutor:
    def __init__(
        self,
        *,
        topic: str,
        subject: str,
        preset: str,
        user_id: str,
        options: Optional[Dict[str, Any]] = None,
        resume_working_memory: Optional[Dict[str, Any]] = None,
        executor: Optional[Any] = None,
        context_manager: Optional[Any] = None,
    ) -> None:
        self.topic = str(topic or "").strip()
        self.subject = str(subject or "").strip()
        self.preset = normalize_preset(preset)
        self.options = dict(options or {})
        self.options["preset"] = self.preset
        self.user_id = str(user_id or "anonymous").strip() or "anonymous"
        self.executor = executor or Executor()
        self.context_manager = context_manager or ContextManager(config=getattr(self.executor, "config", None))
        self.context = CompressedContext(
            user_profile=UserProfile(user_id=self.user_id, preferences={"subject": self.subject} if self.subject else {}),
            system_instructions="Study-material workflow backend tool execution.",
            current_task=self.topic,
            working_memory=dict(resume_working_memory or {}),
        )
        self.context.working_memory["study_options"] = {
            **(
                dict(self.context.working_memory.get("study_options") or {})
                if isinstance(self.context.working_memory.get("study_options"), dict)
                else {}
            ),
            **self.options,
            "strict_llm": True,
        }
        existing_results = self.context.working_memory.get("step_results")
        self.step_results: List[Dict[str, Any]] = [
            dict(item) for item in existing_results if isinstance(item, dict)
        ] if isinstance(existing_results, list) else []

    @property
    def working_memory(self) -> Dict[str, Any]:
        return self.context.working_memory

    async def _execute(
        self,
        *,
        tool: str,
        title: str,
        arguments: Dict[str, Any],
        event_sink: EventSink,
    ) -> StepResult:
        step = PlanStep(
            id=f"{tool}-{uuid.uuid4().hex[:8]}",
            title=title,
            tool=tool,
            arguments=dict(arguments),
            thought=title,
        )
        await event_sink(
            agent_event(
                "tool_call",
                {"step_id": step.id, "name": tool, "title": title, "arguments": dict(arguments)},
            )
        )
        result = await self.executor.execute_step(step, context=self.context, emit_event=event_sink)
        await self.context_manager.on_step_result(self.context, step=step, result=result)
        record = {
            "step_id": result.step_id,
            "tool": result.tool,
            "success": bool(result.success),
            "error": str(result.error or "") or None,
        }
        self.step_results.append(record)
        self.context.working_memory["step_results"] = list(self.step_results)
        await event_sink(
            agent_event(
                "tool_result",
                {
                    "step_id": result.step_id,
                    "name": tool,
                    "title": title,
                    "success": bool(result.success),
                    "output": result.output,
                    "error": result.error,
                },
            )
        )
        return result

    @staticmethod
    def _matching_items(output: Any, point_title: str) -> List[Dict[str, Any]]:
        if not isinstance(output, dict):
            return []
        items = output.get("items") if isinstance(output.get("items"), list) else None
        if items is None:
            return [dict(output)]
        matching = [
            dict(item)
            for item in items
            if isinstance(item, dict)
            and str(item.get("knowledge_point") or point_title).strip() == point_title
        ]
        return matching or [dict(item) for item in items if isinstance(item, dict)]

    @classmethod
    def _evidence_from_result(cls, *, tool: str, output: Any, point_title: str) -> List[Dict[str, Any]]:
        source_class = {
            "web_search_knowledge": "web",
            "wikipedia_search": "wikipedia",
            "mediawiki_search": "mediawiki",
            "browse_web_pages": "page",
        }.get(tool, tool)
        evidence: List[Dict[str, Any]] = []
        for item in cls._matching_items(output, point_title):
            if tool in {"web_search_knowledge", "stackexchange_search", "github_search"}:
                values = item.get("results") if isinstance(item.get("results"), list) else []
                for value in values:
                    if not isinstance(value, dict):
                        continue
                    evidence.append(
                        {
                            "source_class": source_class,
                            "url": value.get("url") or value.get("html_url"),
                            "title": value.get("title") or value.get("full_name") or value.get("name"),
                            "snippet": (
                                value.get("snippet")
                                or value.get("description")
                                or value.get("text")
                                or value.get("question_text")
                                or value.get("top_answer_text")
                                or value.get("readme_excerpt")
                            ),
                        }
                    )
                continue
            if tool == "browse_web_pages":
                values = item.get("pages") if isinstance(item.get("pages"), list) else []
                for value in values:
                    if not isinstance(value, dict):
                        continue
                    evidence.append(
                        {
                            "source_class": source_class,
                            "url": value.get("url"),
                            "title": value.get("title"),
                            "snippet": value.get("text") or value.get("content") or value.get("snippet"),
                        }
                    )
                continue
            evidence.append(
                {
                    "source_class": source_class,
                    "url": item.get("url"),
                    "title": item.get("title") or point_title,
                    "snippet": item.get("summary") or item.get("content") or item.get("snippet"),
                }
            )
        return normalize_evidence(evidence)

    async def research(
        self,
        *,
        plan: Dict[str, Any],
        event_sink: EventSink,
        only_point_ids: Optional[List[str]] = None,
        attempt: int = 0,
    ) -> Dict[str, List[Dict[str, Any]]]:
        raw_points = plan.get("knowledge_points") if isinstance(plan.get("knowledge_points"), list) else []
        points = [dict(item) for item in raw_points if isinstance(item, dict)]
        titles = [str(item.get("title") or "").strip() for item in points if str(item.get("title") or "").strip()]
        self.context.working_memory["split_knowledge_points"] = {"knowledge_points": titles}

        tools = ["web_search_knowledge"]
        if self.preset in {"standard", "deep", "research"}:
            tools.append("wikipedia_search")
        if self.preset == "research":
            tools.append("mediawiki_search")
        if bool(self.options.get("enable_extra_tools")):
            tools.extend(["stackexchange_search", "github_search"])

        if only_point_ids is not None:
            wanted = {str(item or "").strip() for item in only_point_ids if str(item or "").strip()}
            points = [point for point in points if str(point.get("id") or "").strip() in wanted]

        profile = PRESET_PROFILES.get(self.preset) or PRESET_PROFILES["standard"]
        max_consecutive_failures = max(1, int(profile.get("max_consecutive_tool_failures") or 3))
        # 与 backend/agent/config.py 相同的读取方式（STUDY_MATERIALS_SUBAGENT_CONCURRENCY 优先）。
        concurrency = max(
            1,
            env_int("STUDY_MATERIALS_SUBAGENT_CONCURRENCY", env_int("AGENT_SUBAGENT_CONCURRENCY", 3)),
        )

        # 跨并发任务共享的熔断状态：连续失败达到上限即判定检索链路整体不可用。
        # browse_web_pages 是可选深读，失败只单独记录，不触发熔断。
        breaker_lock = asyncio.Lock()
        breaker_state: Dict[str, Any] = {"consecutive_failures": 0, "tools": []}
        browse_failures = 0

        async def _check_breaker() -> None:
            async with breaker_lock:
                if breaker_state["consecutive_failures"] >= max_consecutive_failures:
                    raise ResearchToolOutage(list(breaker_state["tools"]))

        async def _note_tool_result(tool: str, success: bool) -> None:
            nonlocal browse_failures
            if tool == "browse_web_pages":
                if not success:
                    browse_failures += 1
                return
            async with breaker_lock:
                if success:
                    breaker_state["consecutive_failures"] = 0
                    breaker_state["tools"] = []
                    return
                breaker_state["consecutive_failures"] += 1
                breaker_state["tools"].append(tool)
                if breaker_state["consecutive_failures"] >= max_consecutive_failures:
                    raise ResearchToolOutage(list(breaker_state["tools"]))

        async def _research_point(point: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
            point_id = str(point.get("id") or "").strip()
            point_title = str(point.get("title") or "").strip()
            point_evidence: List[Dict[str, Any]] = []
            if not point_id or not point_title:
                return point_id, point_evidence
            queries_raw = point.get("queries") if isinstance(point.get("queries"), list) else []
            queries = [str(query or "").strip() for query in queries_raw if str(query or "").strip()]
            # 重试时轮换查询提示，避免每一轮都用同一个 queries[0]。
            query_hint = queries[attempt % len(queries)] if queries else point_title
            browse_targets: List[str] = []
            for tool in tools:
                await _check_breaker()
                arguments: Dict[str, Any] = {
                    "topic": self.topic,
                    "subject": self.subject,
                    "knowledge_points": [point_title],
                }
                if tool == "web_search_knowledge":
                    arguments.update({"query_hint": query_hint, "preset": self.preset, "limit": 8})
                result = await self._execute(
                    tool=tool,
                    title=f"检索：{point_title}",
                    arguments=arguments,
                    event_sink=event_sink,
                )
                await _note_tool_result(tool, bool(result.success))
                if result.success:
                    extracted = self._evidence_from_result(tool=tool, output=result.output, point_title=point_title)
                    point_evidence.extend(extracted)
                    if tool == "web_search_knowledge":
                        browse_targets = [str(item.get("url") or "") for item in extracted if item.get("url")][:2]

            if self.preset in {"deep", "research"} and browse_targets:
                result = await self._execute(
                    tool="browse_web_pages",
                    title=f"深读：{point_title}",
                    arguments={
                        "knowledge_point": point_title,
                        "urls": browse_targets,
                        "max_pages": 2,
                        "max_chars": 6000,
                    },
                    event_sink=event_sink,
                )
                await _note_tool_result("browse_web_pages", bool(result.success))
                if result.success:
                    page_evidence = self._evidence_from_result(
                        tool="browse_web_pages",
                        output=result.output,
                        point_title=point_title,
                    )
                    page_urls = {str(item.get("url") or "") for item in page_evidence if item.get("url")}
                    point_evidence = [
                        item for item in point_evidence if str(item.get("url") or "") not in page_urls
                    ]
                    point_evidence.extend(page_evidence)
            return point_id, normalize_evidence(point_evidence)

        semaphore = asyncio.Semaphore(concurrency)

        async def _bounded(point: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
            async with semaphore:
                return await _research_point(point)

        tasks = [asyncio.create_task(_bounded(point)) for point in points]
        try:
            gathered = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        # 重试时以 working_memory 中已有证据为底，逐知识点合并而不是整体覆盖。
        research: Dict[str, List[Dict[str, Any]]] = {}
        if only_point_ids is not None:
            existing = self.context.working_memory.get("workflow_research")
            if isinstance(existing, dict):
                research = {str(key): list(value) for key, value in existing.items() if isinstance(value, list)}
        for point_id, evidence in gathered:
            if not point_id:
                continue
            if point_id in research:
                research[point_id] = normalize_evidence(list(research.get(point_id) or []) + list(evidence))
            else:
                research[point_id] = normalize_evidence(evidence)

        self.context.working_memory["workflow_research"] = research
        return research

    async def review(self, *, markdown: str, event_sink: EventSink) -> Dict[str, Any]:
        self.context.working_memory["markdown"] = str(markdown or "")
        self.context.working_memory["assemble_study_archive"] = str(markdown or "")
        result = await self._execute(
            tool="review_content",
            title="独立审查自学资料",
            arguments={"topic": self.topic, "strict_llm": True},
            event_sink=event_sink,
        )
        if not result.success or not isinstance(result.output, dict):
            return {
                "passed": False,
                "issues": [str(result.error or "review_content_failed")],
                "suggestions": [],
                "dimensions": {},
                "draft_hash": draft_hash(markdown),
            }
        return {**result.output, "draft_hash": draft_hash(markdown)}
