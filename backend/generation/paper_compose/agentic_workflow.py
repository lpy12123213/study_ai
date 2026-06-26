from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.agent.executor import Executor
from backend.agent.types import CompressedContext, UserProfile
from backend.generation.agentic.codex_runtime import (
    is_codex_runtime_agent_runtime,
    legacy_agent_fallback_enabled,
    run_codex_runtime_agent_events,
)
from backend.generation.agentic.runtime import AgentRuntime
from backend.generation.agentic.task_specs import build_agent_run_spec_for_task
from backend.generation.agentic.tooling import AgentDecision, ToolResult
from backend.generation.agentic.types import AgentRunSpec, AgentTraceEvent
from backend.llm.client import chat_completion_text, is_llm_configured
from backend.llm.json_utils import extract_first_json_object
from backend.llm.prompts import create_default_prompt_registry


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _text(value: Any, default: str = "") -> str:
    raw = str(value if value is not None else "").strip()
    return raw or default


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _questions_from_output(output: Any) -> List[Dict[str, Any]]:
    if not isinstance(output, dict):
        return []
    candidates: list[Any] = []
    for key in ("questions", "selected_questions", "items"):
        if isinstance(output.get(key), list):
            candidates.extend(output.get(key) or [])
    for slot in _as_list(output.get("slots")):
        if isinstance(slot, dict):
            for key in ("questions", "selected_questions"):
                if isinstance(slot.get(key), list):
                    candidates.extend(slot.get(key) or [])
    return [dict(x) for x in candidates if isinstance(x, dict)]


def _question_ids_from_output(output: Any) -> List[str]:
    ids: list[str] = []
    if not isinstance(output, dict):
        return ids
    for key in ("question_ids", "selected_ids", "ids"):
        ids.extend([_text(x) for x in _as_list(output.get(key)) if _text(x)])
    for question in _questions_from_output(output):
        qid = _text(question.get("question_id") or question.get("id"))
        if qid:
            ids.append(qid)
    for slot in _as_list(output.get("slots")):
        if isinstance(slot, dict):
            for key in ("question_ids", "selected_ids", "ids"):
                ids.extend([_text(x) for x in _as_list(slot.get(key)) if _text(x)])
    seen: set[str] = set()
    out: list[str] = []
    for qid in ids:
        if qid in seen:
            continue
        seen.add(qid)
        out.append(qid)
    return out


class PaperComposePlanner:
    """LLM-backed planner with deterministic fallback for paper-compose tasks."""

    async def next_decision(self, *, spec: AgentRunSpec, state: Dict[str, Any]) -> AgentDecision:
        llm_decision = await self._llm_next_decision(spec=spec, state=state)
        if llm_decision is not None:
            return llm_decision
        return self._fallback_next_decision(spec=spec, state=state)

    async def _llm_next_decision(self, *, spec: AgentRunSpec, state: Dict[str, Any]) -> AgentDecision | None:
        if not is_llm_configured(scope="any"):
            return None
        allowed_tools = [str(x or "").strip() for x in spec.tool_policy.allowed_tools if str(x or "").strip()]
        outputs = state.get("tool_outputs") if isinstance(state.get("tool_outputs"), dict) else {}
        failures = state.get("failures") if isinstance(state.get("failures"), list) else []
        prompt = {
            "goal": spec.goal,
            "subject": spec.subject,
            "requirements": spec.user_requirements,
            "input_payload": spec.input_payload,
            "allowed_tools": allowed_tools,
            "state": {
                "iterations": int(state.get("iterations") or 0),
                "tool_calls": int(state.get("tool_calls") or 0),
                "completed_tools": list(outputs.keys()),
                "last_failures": failures[-3:],
            },
            "decision_schema": {
                "action": "tool | finish",
                "tool_name": "required when action=tool, must be one of allowed_tools",
                "arguments": "object, required when action=tool",
                "role": "planner/searcher/author/solver/composer/compiler/repairer/reviewer",
                "step_id": "stable snake_case id",
                "thought": "brief Chinese rationale",
                "summary": "required when action=finish",
            },
            "guidance": [
                "Use only allowed_tools.",
                "Prefer crawler/local bank first, generate_questions_ai when bank coverage is insufficient.",
                "After questions are available, create_paper, render_paper_latex, then compile_latex_sandbox.",
                "If compile_latex_sandbox failed, call repair_latex before retrying compilation.",
                "Return strict JSON only.",
            ],
        }
        try:
            system_prompt = create_default_prompt_registry().render("paper_compose.planner.v1").content
            text = await chat_completion_text(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                temperature=0.1,
                max_tokens=1600,
                response_format={"type": "json_object"},
                raise_on_fail=True,
                req_id_prefix="paper_agent_planner",
            )
        except Exception:
            return None
        obj = extract_first_json_object(text, default={}) or {}
        if not isinstance(obj, dict):
            return None
        action = _text(obj.get("action")).lower()
        role = _text(obj.get("role"), "planner")
        if action == "finish":
            return AgentDecision.finish(summary=_text(obj.get("summary"), "Agentic 组卷完成"), role=role)
        if action != "tool":
            return None
        tool_name = _text(obj.get("tool_name") or obj.get("name"))
        if tool_name not in allowed_tools:
            return None
        arguments = obj.get("arguments") if isinstance(obj.get("arguments"), dict) else {}
        return AgentDecision.tool(
            name=tool_name,
            arguments=arguments,
            thought=_text(obj.get("thought")),
            role=role,
            step_id=_text(obj.get("step_id") or tool_name),
            metadata={"planner": "llm"},
        )

    def _fallback_next_decision(self, *, spec: AgentRunSpec, state: Dict[str, Any]) -> AgentDecision:
        outputs = state.get("tool_outputs") if isinstance(state.get("tool_outputs"), dict) else {}
        req = spec.input_payload

        if "compose_paper_blueprint" not in outputs and "generate_questions_ai" not in outputs:
            return AgentDecision.tool(
                name="compose_paper_blueprint",
                arguments=dict(req),
                role="planner",
                step_id="compose_blueprint",
                thought="先规划试卷结构并尝试从题库选题。",
            )

        blueprint = outputs.get("compose_paper_blueprint")
        details = outputs.get("batch_get_question_details")
        generated = outputs.get("generate_questions_ai")
        questions = _questions_from_output(details) or _questions_from_output(blueprint) or _questions_from_output(generated)
        qids = _question_ids_from_output(blueprint)

        if qids and "batch_get_question_details" not in outputs:
            return AgentDecision.tool(
                name="batch_get_question_details",
                arguments={"subject": spec.subject, "question_ids": qids, "max_concurrent": 5},
                role="searcher",
                step_id="hydrate_questions",
                thought="补全题干、答案和解析。",
            )

        if not questions and "generate_questions_ai" not in outputs:
            return AgentDecision.tool(
                name="generate_questions_ai",
                arguments={
                    "subject": spec.subject,
                    "topic": _text(req.get("topic") or req.get("paperName") or req.get("paper_name")),
                    "count": int(req.get("count") or 6),
                    "difficulty": _text(req.get("difficulty"), "中等"),
                    "question_type": _text(req.get("question_type"), "解答题"),
                },
                role="author",
                step_id="generate_questions_ai",
                thought="题库候选不足，转为原创题生成。",
            )

        if "create_paper" not in outputs:
            return AgentDecision.tool(
                name="create_paper",
                arguments={
                    "subject": spec.subject,
                    "paper_name": _text(req.get("paperName") or req.get("paper_name"), "Agentic 生成试卷"),
                    "questions": questions,
                },
                role="composer",
                step_id="create_paper",
                thought="保存试卷快照。",
            )

        if "render_paper_latex" not in outputs:
            return AgentDecision.tool(
                name="render_paper_latex",
                arguments={"include_stem": True, "include_answer": True, "include_analysis": True},
                role="composer",
                step_id="render_latex",
                thought="生成考试版式 LaTeX。",
            )

        if "compile_latex_sandbox" not in outputs:
            return AgentDecision.tool(
                name="compile_latex_sandbox",
                arguments={},
                role="compiler",
                step_id="compile_pdf",
                thought="使用配置的 LaTeX 后端编译 PDF。",
            )

        return AgentDecision.finish(summary="Agentic 组卷完成", role="reviewer")


class PaperComposeToolExecutor:
    def __init__(self, *, user_id: str, request: Dict[str, Any]) -> None:
        subject = _text(request.get("subject"))
        topic = _text(request.get("topic") or request.get("paperName") or request.get("paper_name"))
        self.context = CompressedContext(
            user_profile=UserProfile(user_id=_text(user_id, "anonymous"), preferences={"subject": subject}),
            system_instructions="",
            current_task=topic or subject or "组卷",
        )
        self.executor = Executor()

    async def execute_tool(
        self,
        *,
        name: str,
        arguments: Dict[str, Any],
        spec: AgentRunSpec,
        state: Dict[str, Any],
    ) -> ToolResult:
        try:
            output = await self.executor.tool_registry.call_tool(name=name, arguments=arguments, ctx=self.context)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

        outputs = state.get("tool_outputs")
        if not isinstance(outputs, dict):
            outputs = {}
            state["tool_outputs"] = outputs
        outputs[name] = output
        return ToolResult(success=True, output=output)


def _trace_to_sse(event: AgentTraceEvent) -> Dict[str, Any]:
    payload = event.to_task_event()
    payload["type"] = event.event
    return payload


def _tool_call_step(event: AgentTraceEvent) -> Dict[str, Any]:
    data = event.data
    name = _text(data.get("name"))
    return {
        "type": "step",
        "step": {
            "id": event.step_id or name,
            "title": name or "agent_tool",
            "thought": _text(data.get("thought")),
            "status": "running",
            "startTime": _now_iso(),
            "toolName": name,
            "input": data.get("arguments") if isinstance(data.get("arguments"), dict) else {},
        },
    }


def _tool_result_step(event: AgentTraceEvent) -> Dict[str, Any]:
    data = event.data
    name = _text(data.get("name"))
    success = bool(data.get("success"))
    return {
        "type": "step",
        "step": {
            "id": event.step_id or name,
            "title": name or "agent_tool",
            "status": "completed" if success else "failed",
            "endTime": _now_iso(),
            "toolName": name,
            "output": data.get("output") if success else {"error": data.get("error")},
        },
    }


def _result_from_context(executor: PaperComposeToolExecutor, request: Dict[str, Any]) -> Dict[str, Any]:
    memory = executor.context.working_memory
    return {
        "paper_id": memory.get("paper_id"),
        "paper_name": _text(request.get("paperName") or request.get("paper_name"), "Agentic 生成试卷"),
        "subject": _text(request.get("subject")),
        "topic": _text(request.get("topic")),
        "question_count": len(_questions_from_output(memory.get("question_details")))
        or len(_questions_from_output(memory.get("generated_questions_ai")))
        or len(_as_list((memory.get("paper") or {}).get("questions") if isinstance(memory.get("paper"), dict) else [])),
        "tex_url": memory.get("tex_url"),
        "pdf_url": memory.get("pdf_url"),
        "native_agentic": True,
    }


async def _run_agentic_paper_events(
    request: Dict[str, Any],
    *,
    user_id: str,
    task_type: str,
) -> AsyncIterator[Dict[str, Any]]:
    req = dict(request or {})
    spec = build_agent_run_spec_for_task(task_type=task_type, request=req)
    if spec is None:
        yield {"type": "error", "error": "agent_spec_missing"}
        return

    if is_codex_runtime_agent_runtime():
        codex_terminal = False
        codex_succeeded = False
        last_error_event: Optional[Dict[str, Any]] = None
        async for event in run_codex_runtime_agent_events(
            task_type=task_type,
            request=req,
            user_id=user_id,
            task_id=str(req.get("taskId") or req.get("task_id") or ""),
            spec=spec,
            final_event_type="result",
        ):
            if event.get("type") == "error":
                codex_terminal = True
                last_error_event = event
                # A successful final result can follow recoverable tool errors.
                # Defer failure handling until the Codex stream is exhausted.
                continue
            if event.get("type") in {"result", "done", "pending_review"}:
                codex_terminal = True
                codex_succeeded = True
            yield event
        if codex_terminal:
            if not codex_succeeded and isinstance(last_error_event, dict):
                yield last_error_event
            return
        if not legacy_agent_fallback_enabled():
            return
        # Only a stream that ended without any terminal event may use the
        # compatibility runner. Explicit Codex success/error is authoritative.
        yield {
            "type": "progress",
            "progress": 1.0,
            "stage": "codex_runtime_fallback",
            "data": {"code": "codex_runtime_ended_without_terminal_event"},
        }

    executor = PaperComposeToolExecutor(user_id=user_id, request=req)
    runtime = AgentRuntime(planner=PaperComposePlanner(), tool_executor=executor)
    yield {"type": "progress", "progress": 3.0, "stage": "agentic_start"}

    async for event in runtime.run(spec):
        yield _trace_to_sse(event)
        if event.event == "tool_call":
            yield _tool_call_step(event)
        elif event.event == "tool_result":
            yield _tool_result_step(event)
        elif event.event == "error":
            yield {"type": "error", "error": _text(event.data.get("error"), "agentic_full_paper_failed"), "data": event.data}
            return
        elif event.event == "finish":
            yield {"type": "progress", "progress": 100.0, "stage": "agentic_done"}
            yield {"type": "result", "result": _result_from_context(executor, req)}
            return


async def run_agentic_full_paper_events(
    request: Dict[str, Any],
    *,
    user_id: str,
) -> AsyncIterator[Dict[str, Any]]:
    async for event in _run_agentic_paper_events(request, user_id=user_id, task_type="paper_generate_full"):
        yield event


async def run_agentic_blueprint_paper_events(
    request: Dict[str, Any],
    *,
    user_id: str,
) -> AsyncIterator[Dict[str, Any]]:
    async for event in _run_agentic_paper_events(request, user_id=user_id, task_type="paper_compose"):
        yield event
