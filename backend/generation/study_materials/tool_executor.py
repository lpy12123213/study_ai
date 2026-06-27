from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.agent.context import ContextManager
from backend.agent.executor import Executor
from backend.agent.types import CompressedContext, PlanStep, StepResult, UserProfile, agent_event
from backend.generation.study_materials.quality_gate import draft_hash, normalize_evidence, normalize_preset

EventSink = Callable[[Dict[str, Any]], Awaitable[None]]


class StudyMaterialsToolExecutor:
    def __init__(
        self,
        *,
        topic: str,
        subject: str,
        preset: str,
        user_id: str,
        resume_working_memory: Optional[Dict[str, Any]] = None,
        executor: Optional[Any] = None,
        context_manager: Optional[Any] = None,
    ) -> None:
        self.topic = str(topic or "").strip()
        self.subject = str(subject or "").strip()
        self.preset = normalize_preset(preset)
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
            "preset": self.preset,
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
            if tool == "web_search_knowledge":
                values = item.get("results") if isinstance(item.get("results"), list) else []
                for value in values:
                    if not isinstance(value, dict):
                        continue
                    evidence.append(
                        {
                            "source_class": source_class,
                            "url": value.get("url"),
                            "title": value.get("title"),
                            "snippet": value.get("snippet") or value.get("description") or value.get("text"),
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

    async def research(self, *, plan: Dict[str, Any], event_sink: EventSink) -> Dict[str, List[Dict[str, Any]]]:
        raw_points = plan.get("knowledge_points") if isinstance(plan.get("knowledge_points"), list) else []
        points = [dict(item) for item in raw_points if isinstance(item, dict)]
        titles = [str(item.get("title") or "").strip() for item in points if str(item.get("title") or "").strip()]
        self.context.working_memory["split_knowledge_points"] = {"knowledge_points": titles}

        tools = ["web_search_knowledge"]
        if self.preset in {"standard", "deep", "research"}:
            tools.append("wikipedia_search")
        if self.preset == "research":
            tools.append("mediawiki_search")

        research: Dict[str, List[Dict[str, Any]]] = {}
        browse_urls: Dict[str, List[str]] = {}
        for point in points:
            point_id = str(point.get("id") or "").strip()
            point_title = str(point.get("title") or "").strip()
            if not point_id or not point_title:
                continue
            point_evidence: List[Dict[str, Any]] = []
            queries = point.get("queries") if isinstance(point.get("queries"), list) else []
            query_hint = str(queries[0] if queries else point_title).strip()
            for tool in tools:
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
                if result.success:
                    extracted = self._evidence_from_result(tool=tool, output=result.output, point_title=point_title)
                    point_evidence.extend(extracted)
                    if tool == "web_search_knowledge":
                        browse_urls[point_id] = [str(item.get("url") or "") for item in extracted if item.get("url")][:2]

            if self.preset in {"deep", "research"} and browse_urls.get(point_id):
                result = await self._execute(
                    tool="browse_web_pages",
                    title=f"深读：{point_title}",
                    arguments={
                        "knowledge_point": point_title,
                        "urls": browse_urls[point_id],
                        "max_pages": 2,
                        "max_chars": 6000,
                    },
                    event_sink=event_sink,
                )
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
            research[point_id] = normalize_evidence(point_evidence)

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
