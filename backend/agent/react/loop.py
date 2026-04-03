from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from backend.agent.config import AgentConfig
from backend.agent.mcp.registry import MCPToolRegistry
from backend.agent.react.prompts import build_react_messages
from backend.agent.types import ActionResults, CompressedContext, ExecutionPlan, PlanStep, agent_event
from backend.core.logging_utils import get_logger
from backend.llm.client import chat_completion, is_llm_configured

logger = get_logger(__name__)


def _strip_code_fences(text: str) -> str:
    s = (text or "").strip()
    if not s.startswith("```"):
        return s
    # ```json ... ```
    lines = s.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_first_json_object(text: str) -> Dict[str, Any]:
    raw = _strip_code_fences(text)
    if not raw:
        return {}
    left = raw.find("{")
    right = raw.rfind("}")
    if left < 0 or right <= left:
        return {}
    candidate = raw[left : right + 1].strip()
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _clip_text(text: str, *, max_chars: int) -> str:
    s = str(text or "")
    if len(s) <= max_chars:
        return s
    return s[: max(0, max_chars - 1)].rstrip() + "…"


def _format_observation(step_results: List[Any]) -> str:
    lines: List[str] = []
    for r in step_results or []:
        tool = str(getattr(r, "tool", "") or "").strip()
        ok = bool(getattr(r, "success", False))
        err = str(getattr(r, "error", "") or "").strip()
        out = getattr(r, "output", None)
        out_preview = ""
        if out is not None:
            try:
                out_preview = json.dumps(out, ensure_ascii=False)
            except Exception:
                out_preview = str(out)
            out_preview = _clip_text(out_preview, max_chars=260)

        if ok:
            if out_preview:
                lines.append(f"- {tool}: ok; output={out_preview}")
            else:
                lines.append(f"- {tool}: ok")
        else:
            lines.append(f"- {tool}: failed; error={_clip_text(err, max_chars=220) or 'unknown_error'}")
        if len(lines) >= 6:
            lines.append("- ...")
            break
    return "\n".join(lines).strip()


@dataclass
class ReActDecision:
    thought: str = ""
    action: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    note: str = ""


Decider = Callable[[List[Dict[str, str]]], Awaitable[Dict[str, Any]]]
ExecuteStep = Callable[[PlanStep], AsyncIterator[Dict[str, Any]]]


class ReActLoop:
    def __init__(
        self,
        *,
        config: Optional[AgentConfig] = None,
        tool_registry: MCPToolRegistry,
        decide_next: Optional[Decider] = None,
    ) -> None:
        self.config = config or AgentConfig.from_env()
        self.tool_registry = tool_registry
        self._decide_next = decide_next

    async def _llm_decide(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        model = str(self.config.planner_model or "").strip()
        if not model or not is_llm_configured():
            return {}

        max_tokens = 900
        try:
            raw = int((self.config.react_max_iterations or 0))
            _ = raw
        except Exception:
            pass

        try:
            res = await chat_completion(
                messages=messages,
                model=model,
                temperature=0.2,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                stream=False,
                retries=3,
                req_id_prefix="react",
            )
        except Exception:
            logger.debug("react_llm_decide_failed", exc_info=True)
            return {}

        return _extract_first_json_object(getattr(res, "content", "") or "")

    async def _decide(self, messages: List[Dict[str, str]]) -> ReActDecision:
        if self._decide_next is not None:
            obj = await self._decide_next(messages)
        else:
            obj = await self._llm_decide(messages)

        if not isinstance(obj, dict):
            obj = {}

        thought = str(obj.get("thought") or "").strip()
        action = str(obj.get("action") or "").strip()
        note = str(obj.get("note") or "").strip()
        args = obj.get("arguments")
        arguments = dict(args) if isinstance(args, dict) else {}
        return ReActDecision(thought=thought, action=action, arguments=arguments, note=note)

    def _tool_exists(self, name: str) -> bool:
        try:
            return self.tool_registry.get_tool(name) is not None
        except Exception:
            return False

    async def run(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        topic: str,
        subject: str,
        execute_concrete_step: ExecuteStep,
        max_iterations: int,
        skip_export: bool,
    ) -> AsyncIterator[Dict[str, Any]]:
        max_iterations = int(max_iterations or 0)
        if max_iterations <= 0:
            max_iterations = int(self.config.react_max_iterations or 20)
        max_iterations = max(1, min(max_iterations, 50))

        tools = self.tool_registry.list_tools()

        scratch: List[Dict[str, Any]] = []

        yield agent_event("status", {"content": f"ReAct 模式：动态调用工具（最多 {max_iterations} 轮）…"})

        for i in range(max_iterations):
            if bool(ctx.working_memory.get("_abort_execution")):
                break

            scratchpad_text = "\n".join(
                [
                    f"{idx + 1}. Thought: {_clip_text(str(x.get('thought') or ''), max_chars=120)}\n"
                    f"   Action: {x.get('action')}\n"
                    f"   Observation: {_clip_text(str(x.get('observation') or ''), max_chars=180)}"
                    for idx, x in enumerate(scratch[-8:])
                    if isinstance(x, dict)
                ]
            ).strip()

            messages = build_react_messages(
                ctx=ctx,
                topic=topic,
                subject=subject,
                tools=tools,
                scratchpad=scratchpad_text,
                iteration=i,
                max_iterations=max_iterations,
            )

            decision = await self._decide(messages)

            if decision.thought:
                yield agent_event("status", {"content": decision.thought})

            action = (decision.action or "").strip()
            action_norm = action.lower().replace("-", "").replace("_", "")
            if action_norm in {"finish", "final", "done", "stop"}:
                break

            if not action:
                scratch.append(
                    {
                        "thought": decision.thought,
                        "action": "",
                        "observation": "empty_action",
                    }
                )
                yield agent_event("status", {"content": "ReAct：未返回 action，已跳过本轮。"})
                continue

            if not self._tool_exists(action):
                scratch.append(
                    {
                        "thought": decision.thought,
                        "action": action,
                        "observation": f"tool_not_found: {action}",
                    }
                )
                yield agent_event("status", {"content": f"ReAct：未知工具 {action}，请更换 action。"})
                continue

            step = PlanStep(
                id=f"react-{i + 1}-{uuid.uuid4().hex[:8]}",
                title=f"ReAct: {action}",
                tool=action,
                arguments=decision.arguments,
                thought=decision.thought,
            )

            before_n = len(results.step_results)
            async for evt in execute_concrete_step(step):
                yield evt
            after = results.step_results[before_n:]
            observation = _format_observation(after)
            scratch.append(
                {
                    "thought": decision.thought,
                    "action": action,
                    "arguments": decision.arguments,
                    "observation": observation,
                }
            )

        # Finalization: ensure we end up with a Markdown archive + (optional) exports + review.
        if bool(ctx.working_memory.get("_abort_execution")):
            return

        yield agent_event("status", {"content": "ReAct：收尾（组装/保存/导出/审查）…"})

        # Build a minimal plan placeholder for debugging / downstream reflector.
        ctx.working_memory.setdefault(
            "react_plan",
            ExecutionPlan(topic=topic, steps=[], rationale="react").__dict__,
        )

        export_tools = {
            "export_study_markdown",
            "convert_markdown_to_latex",
            "refine_latex",
            "compile_latex_to_pdf",
        }

        finalize_steps: List[PlanStep] = [
            PlanStep(
                id=f"react-final-assemble-{uuid.uuid4().hex[:8]}",
                title="Assemble Study Archive",
                tool="assemble_study_archive",
                arguments={"topic": topic, "subject": subject},
                thought="将已有内容组装为最终自学档案 Markdown。",
            ),
            PlanStep(
                id=f"react-final-save-{uuid.uuid4().hex[:8]}",
                title="Save Markdown",
                tool="save_markdown_file",
                arguments={"topic": topic},
                thought="保存 Markdown 到本地文件，便于归档。",
            ),
            PlanStep(
                id=f"react-final-export-{uuid.uuid4().hex[:8]}",
                title="Export Markdown",
                tool="export_study_markdown",
                arguments={},
                thought="发布 Markdown 下载链接。",
            ),
            PlanStep(
                id=f"react-final-tex-{uuid.uuid4().hex[:8]}",
                title="Convert Markdown to LaTeX",
                tool="convert_markdown_to_latex",
                arguments={"topic": topic, "subject": subject},
                thought="把 Markdown 转成 LaTeX（ElegantBook）。",
            ),
            PlanStep(
                id=f"react-final-refine-tex-{uuid.uuid4().hex[:8]}",
                title="Refine LaTeX",
                tool="refine_latex",
                arguments={"topic": topic, "subject": subject},
                thought="可选：修订 LaTeX，提升编译成功率与排版质量。",
            ),
            PlanStep(
                id=f"react-final-pdf-{uuid.uuid4().hex[:8]}",
                title="Compile LaTeX to PDF",
                tool="compile_latex_to_pdf",
                arguments={"topic": topic},
                thought="编译 LaTeX 为 PDF。",
            ),
            PlanStep(
                id=f"react-final-review-{uuid.uuid4().hex[:8]}",
                title="Review Content",
                tool="review_content",
                arguments={"topic": topic},
                thought="对最终内容做审查，发现遗漏/错误则提示问题。",
            ),
        ]

        # Skip already-produced artifacts where possible (best-effort).
        already_md = bool(
            isinstance(ctx.working_memory.get("markdown"), str) and str(ctx.working_memory.get("markdown") or "").strip()
        )
        already_saved = bool(str(ctx.working_memory.get("archive_path") or "").strip())
        already_reviewed = isinstance(ctx.working_memory.get("review_content"), dict)

        for step in finalize_steps:
            if bool(ctx.working_memory.get("_abort_execution")):
                break

            if already_md and step.tool == "assemble_study_archive":
                continue
            if already_saved and step.tool == "save_markdown_file":
                continue
            if already_reviewed and step.tool == "review_content":
                continue
            if skip_export and step.tool in export_tools:
                continue

            async for evt in execute_concrete_step(step):
                yield evt
