from __future__ import annotations

import asyncio
import inspect
import json
import os
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from backend.agent.config import AgentConfig
from backend.agent.mcp.registry import MCPToolRegistry
from backend.agent.tools.registry import TOOL_MIXINS
from backend.agent.tools.schemas import get_tool_input_schema
from backend.agent.tools.utils.schema_validation import validate_and_coerce_args
from backend.agent.tools.utils.text_utils import _looks_truncated_markdown, _repair_incomplete_markdown, _trim_overlap
from backend.agent.types import CompressedContext, PlanStep, StepResult, agent_event
from backend.core import business_metrics
from backend.core.logging_utils import get_logger
from backend.core.settings import (
    API_TIMEOUT,
    LESSON_PLAN_MAX_TOKENS,
    LESSON_PLAN_TEMPERATURE,
    STUDY_MATERIALS_THINKING_EFFORT_DEFAULT,
)
from backend.llm.client import ChatCompletionResult, chat_completion
from backend.llm.json_utils import extract_first_json_object

_emit_event_var: ContextVar[Optional[Callable[[Dict[str, Any]], Awaitable[None]]]] = ContextVar(
    "agent_emit_event",
    default=None,
)

logger = get_logger(__name__)


class _ToolBox(
    *TOOL_MIXINS,
):
    """Composition wrapper around tool mixins.

    Tool mixins were historically inherited directly by `Executor`, which grew a
    long and fragile multiple-inheritance chain. `_ToolBox` keeps the mixins
    isolated and delegates unknown attributes back to the owning `Executor`.
    """

    def __init__(self, *, executor: "Executor") -> None:
        self._executor = executor
        # Many tools expect `self.config` to exist.
        self.config = executor.config

    def __getattr__(self, name: str) -> Any:  # pragma: no cover (simple delegation)
        return getattr(self._executor, name)


class Executor:
    def __init__(self, *, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.from_env()
        self._toolbox = _ToolBox(executor=self)
        self._tool_handlers = self._build_tool_handlers()
        self._tool_registry = self._build_tool_registry()

    @property
    def tool_registry(self) -> MCPToolRegistry:
        return self._tool_registry

    def _build_tool_handlers(self) -> Dict[str, Callable[[Dict[str, Any], CompressedContext], Awaitable[Any]]]:
        """Build a stable `{tool_name -> handler}` dispatch table.

        This detects duplicate registrations early (avoids silent MRO overrides).
        """

        handlers: Dict[str, Callable[[Dict[str, Any], CompressedContext], Awaitable[Any]]] = {}
        for mixin in TOOL_MIXINS:
            # Some tool groups are exposed via composite mixins (for example `LatexToolsMixin`),
            # so inherited `_tool_*` methods must also be discoverable here.
            for attr_name in dir(mixin):
                value = getattr(mixin, attr_name, None)
                if not attr_name.startswith("_tool_"):
                    continue
                if not callable(value):
                    continue
                tool_name = attr_name[len("_tool_") :].strip()
                if not tool_name:
                    continue
                if tool_name in handlers:
                    raise RuntimeError(f"duplicate_tool_registration: {tool_name}")
                handlers[tool_name] = getattr(self._toolbox, attr_name)
        return handlers

    def _build_tool_registry(self) -> MCPToolRegistry:
        reg = MCPToolRegistry()

        for name, handler in self._tool_handlers.items():
            doc = inspect.getdoc(handler) or ""
            first_line = (doc.splitlines()[0].strip() if doc else "").strip()
            desc = first_line or name
            reg.register(
                name=name,
                description=desc,
                input_schema=get_tool_input_schema(name),
                execute=handler,
            )

        return reg

    @staticmethod
    def _coerce_bool(value: Any, *, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return bool(default)
        s = str(value).strip().lower()
        if s in {"1", "true", "yes", "y", "on"}:
            return True
        if s in {"0", "false", "no", "n", "off"}:
            return False
        return bool(default)

    def _strict_llm(self, ctx: CompressedContext, args: Optional[Dict[str, Any]] = None) -> bool:
        v: Any = None
        if isinstance(args, dict) and "strict_llm" in args:
            v = args.get("strict_llm")
        else:
            study_opts = ctx.working_memory.get("study_options")
            study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
            v = study_opts.get("strict_llm")
        if v is None:
            v = os.getenv("STUDY_MATERIALS_STRICT_LLM")
        # Default to True (user request: reduce fallbacks, fail fast on LLM errors).
        return self._coerce_bool(v, default=True)

    async def _emit_event(self, event: str, data: Optional[Dict[str, Any]] = None) -> None:
        cb = _emit_event_var.get()
        if cb is None:
            return
        try:
            await cb(agent_event(str(event or ""), dict(data or {})))
        except Exception:
            logger.warning("agent_emit_event_failed", exc_info=True)
            return

    async def _emit_status(self, content: str) -> None:
        text = str(content or "").strip()
        if not text:
            return
        await self._emit_event("status", {"content": text})

    async def _emit_progress(self, *, percent: int, stage: str = "", current: int = 0, total: int = 0) -> None:
        p = int(percent or 0)
        if p < 0:
            p = 0
        if p > 100:
            p = 100
        payload: Dict[str, Any] = {"percent": p}
        s = str(stage or "").strip()
        if s:
            payload["stage"] = s
        if int(current or 0) > 0:
            payload["current"] = int(current)
        if int(total or 0) > 0:
            payload["total"] = int(total)
        await self._emit_event("progress", payload)

    async def execute_step(
        self,
        step: PlanStep,
        *,
        context: CompressedContext,
        emit_event: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> StepResult:
        tool = (step.tool or "").strip()
        handler = self._tool_handlers.get(tool)
        if handler is None:
            return StepResult(step_id=step.id, tool=tool, success=False, error=f"Unknown tool: {tool}")

        # Validate/coerce arguments against tool schema (prevents shape mismatches from propagating).
        try:
            schema = get_tool_input_schema(tool)
            args = validate_and_coerce_args(schema=schema, args=step.arguments or {}, tool_name=tool)
        except (KeyError, TypeError, ValueError) as exc:
            return StepResult(step_id=step.id, tool=tool, success=False, error=str(exc))

        timeout_raw = (
            os.getenv("STUDY_MATERIALS_STEP_TIMEOUT_S")
            or os.getenv("AGENT_STEP_TIMEOUT_S")
            or os.getenv("API_TIMEOUT")
            or str(API_TIMEOUT)
        )
        try:
            timeout_s = float(timeout_raw)
        except (TypeError, ValueError):
            timeout_s = float(API_TIMEOUT or 120)
        timeout_s = max(30.0, min(timeout_s, 60.0 * 30.0))  # clamp to [30s, 30m]

        # LaTeX export pipeline can involve multiple long LLM calls (chunking + continuations).
        if tool in {"convert_markdown_to_latex", "refine_latex"}:
            latex_step_timeout_raw = os.getenv("STUDY_MATERIALS_LATEX_STEP_TIMEOUT_S") or ""
            try:
                latex_step_timeout_s = float(latex_step_timeout_raw) if latex_step_timeout_raw.strip() else 0.0
            except (TypeError, ValueError):
                latex_step_timeout_s = 0.0
            # Default to the max clamp (30m). Even if configured, keep a sensible minimum
            # because LaTeX export is typically the slowest stage and otherwise times out
            # under large documents.
            if latex_step_timeout_s <= 0:
                latex_step_timeout_s = 60.0 * 30.0
            latex_step_timeout_s = max(60.0 * 5.0, min(latex_step_timeout_s, 60.0 * 30.0))
            timeout_s = max(timeout_s, latex_step_timeout_s)

        # PDF compilation should have a tighter default (avoid hanging on TeX package installs).
        if tool == "compile_latex_to_pdf":
            compile_timeout_raw = (
                os.getenv("AGENT_LATEX_COMPILE_TIMEOUT_S")
                or os.getenv("PAPER_EXPORT_LATEX_TIMEOUT_S")
                or os.getenv("STUDY_MATERIALS_LATEX_TIMEOUT_S")
                or ""
            )
            try:
                compile_timeout_s = float(compile_timeout_raw) if str(compile_timeout_raw).strip() else 0.0
            except (TypeError, ValueError):
                compile_timeout_s = 0.0
            if compile_timeout_s <= 0:
                compile_timeout_s = 30.0
            compile_timeout_s = max(30.0, min(compile_timeout_s, 60.0 * 20.0))
            timeout_s = compile_timeout_s

        token = _emit_event_var.set(emit_event)
        tool_success = False
        try:
            output = await asyncio.wait_for(handler(args, context), timeout=timeout_s)
            tool_success = True
            return StepResult(step_id=step.id, tool=tool, success=True, output=output)
        except asyncio.TimeoutError:
            return StepResult(
                step_id=step.id,
                tool=tool,
                success=False,
                error=f"Tool timeout after {int(timeout_s)}s: {tool}",
            )
        except Exception as exc:  # pragma: no cover (best-effort safety)
            logger.warning("agent_tool_step_failed", extra={"tool": tool}, exc_info=True)
            return StepResult(step_id=step.id, tool=tool, success=False, error=str(exc))
        finally:
            business_metrics.record_tool_call(name=tool, success=tool_success)
            try:
                _emit_event_var.reset(token)
            except ValueError:
                logger.debug("executor_reset_emit_event_var_failed", exc_info=True)

    async def _call_llm(
        self,
        *,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        reasoning: Optional[Dict[str, Any]] = None,
        response_format: Optional[Dict[str, Any]] = None,
        raise_on_fail: bool = False,
        retries: Optional[int] = None,
        req_id_prefix: str = "exec",
    ) -> ChatCompletionResult:
        normalized_model = str(model or "").strip()
        if not normalized_model:
            if raise_on_fail:
                raise RuntimeError("llm_not_configured")
            return ChatCompletionResult()

        def _truthy(raw: str) -> bool:
            s = (raw or "").strip().lower()
            return s in {"1", "true", "yes", "y", "on"}

        def _default_reasoning_cfg() -> Optional[Dict[str, Any]]:
            # Default to enabled (requested: always use "thinking mode" unless explicitly disabled).
            enabled_raw = os.getenv("STUDY_MATERIALS_THINKING_MODE") or os.getenv("STUDY_MATERIALS_REASONING") or "1"
            if (enabled_raw or "").strip().lower() in {"0", "false", "no", "off"}:
                return None

            effort_raw = os.getenv("STUDY_MATERIALS_THINKING_EFFORT") or os.getenv("STUDY_MATERIALS_REASONING_EFFORT")
            if not str(effort_raw or "").strip():
                effort_raw = STUDY_MATERIALS_THINKING_EFFORT_DEFAULT or "xhigh"
            effort = (effort_raw or "").strip().lower().replace("-", "").replace("_", "")
            if effort in {"max", "maximum", "highest"}:
                effort = "xhigh"
            allowed = {"none", "minimal", "low", "medium", "high", "xhigh"}
            if effort not in allowed:
                effort = "xhigh"

            exclude_raw = os.getenv("STUDY_MATERIALS_REASONING_EXCLUDE") or "0"
            exclude = _truthy(exclude_raw)
            return {"effort": effort, "exclude": exclude}

        default_reasoning = _default_reasoning_cfg()
        if reasoning is None:
            # No call-site override: use env defaults.
            reasoning = default_reasoning
        else:
            # Call-site override should win.
            if default_reasoning is None:
                reasoning = dict(reasoning)
            else:
                merged = dict(default_reasoning)
                merged.update(dict(reasoning))
                reasoning = merged

        stream_reasoning = _truthy(
            os.getenv("STUDY_MATERIALS_STREAM_REASONING") or os.getenv("AGENT_STREAM_REASONING") or "1"
        )

        async def _emit_thinking_delta(text: str) -> None:
            cb = _emit_event_var.get()
            if cb is None:
                return
            t = str(text or "")
            if not t:
                return
            # Keep each event small to avoid blowing up the in-memory SSE backlog.
            max_chars = int(os.getenv("STUDY_MATERIALS_REASONING_EVENT_MAX_CHARS") or "1200")
            if max_chars <= 0:
                await cb(agent_event("thinking", {"content": t, "delta": True}))
                return
            for i in range(0, len(t), max_chars):
                chunk = t[i : i + max_chars]
                if chunk:
                    await cb(agent_event("thinking", {"content": chunk, "delta": True}))

        def _max_retries() -> int:
            raw = str(
                retries
                if retries is not None
                else os.getenv("STUDY_MATERIALS_LLM_RETRIES")
                or os.getenv("LESSON_PLAN_LLM_RETRIES")
                or os.getenv("AGENT_LLM_RETRIES")
                or "3"
            ).strip()
            try:
                v = int(raw)
            except (TypeError, ValueError):
                v = 3
            return max(1, min(v, 10))

        reasoning_emit_chars = int(os.getenv("STUDY_MATERIALS_REASONING_EMIT_CHARS") or "240")
        if reasoning_emit_chars <= 0:
            reasoning_emit_chars = 240
        reasoning_emit_interval_s = float(os.getenv("STUDY_MATERIALS_REASONING_EMIT_INTERVAL_S") or "0.25")
        reasoning_emit_interval_s = max(0.05, min(reasoning_emit_interval_s, 2.0))

        return await chat_completion(
            messages=messages,
            model=normalized_model,
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            response_format=response_format,
            reasoning=reasoning,
            stream=stream_reasoning,
            on_reasoning_delta=_emit_thinking_delta,
            reasoning_emit_chars=reasoning_emit_chars,
            reasoning_emit_interval_s=reasoning_emit_interval_s,
            raise_on_fail=raise_on_fail,
            retries=_max_retries(),
            req_id_prefix=req_id_prefix,
        )

    async def _call_llm_text(
        self,
        *,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = LESSON_PLAN_TEMPERATURE,
        max_tokens: int = LESSON_PLAN_MAX_TOKENS,
        reasoning: Optional[Dict[str, Any]] = None,
        response_format: Optional[Dict[str, Any]] = None,
        raise_on_fail: bool = False,
        retries: Optional[int] = None,
    ) -> str:
        res = await self._call_llm(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning=reasoning,
            response_format=response_format,
            raise_on_fail=raise_on_fail,
            retries=retries,
            req_id_prefix="exec-text",
        )
        return str(res.content or "")

    async def _call_llm_response(
        self,
        *,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = LESSON_PLAN_TEMPERATURE,
        max_tokens: int = LESSON_PLAN_MAX_TOKENS,
        reasoning: Optional[Dict[str, Any]] = None,
        raise_on_fail: bool = False,
        retries: Optional[int] = None,
    ) -> Dict[str, Any]:
        res = await self._call_llm(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning=reasoning,
            raise_on_fail=raise_on_fail,
            retries=retries,
            req_id_prefix="exec-resp",
        )
        return {
            "content": str(res.content or ""),
            "finish_reason": str(res.finish_reason or ""),
            "usage": dict(res.usage or {}),
        }

    async def _call_llm_markdown_with_continuation(
        self,
        *,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = LESSON_PLAN_TEMPERATURE,
        max_tokens: int = LESSON_PLAN_MAX_TOKENS,
        reasoning: Optional[Dict[str, Any]] = None,
        continuation_context: Optional[Dict[str, Any]] = None,
        max_continuations: int = 2,
        raise_on_fail: bool = False,
        retries: Optional[int] = None,
    ) -> Dict[str, Any]:
        res = await self._call_llm_response(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning=reasoning,
            raise_on_fail=raise_on_fail,
            retries=retries,
        )
        content = str(res.get("content") or "").strip()
        finish_reason = str(res.get("finish_reason") or "").strip().lower()
        usage = res.get("usage") if isinstance(res.get("usage"), dict) else {}
        conts = 0

        def _is_truncated(text: str, fr: str, usage_obj: Any) -> bool:
            if (fr or "").strip().lower() == "length":
                return True
            if _looks_truncated_markdown(text):
                return True
            if isinstance(usage_obj, dict):
                try:
                    ct = int(usage_obj.get("completion_tokens") or 0)
                except (TypeError, ValueError):
                    ct = 0
                if ct and max_tokens and ct >= int(max_tokens * 0.95):
                    return True
            return False

        try:
            max_continuations = int(max_continuations or 0)
        except (TypeError, ValueError):
            max_continuations = 0
        max_continuations = max(0, min(max_continuations, 5))

        ctx_obj = dict(continuation_context) if isinstance(continuation_context, dict) else {}
        while conts < max_continuations and content and _is_truncated(content, finish_reason, usage):
            tail = content[-1600:]
            payload = dict(ctx_obj)
            payload["existing_markdown_tail"] = tail
            payload["instructions"] = (
                "The previous output appears truncated. Continue strictly from the end of existing_markdown_tail.\n"
                "Output only the Markdown that must be appended. Do not repeat previous content.\n"
                "If the last line is an unfinished sentence, formula, or list, complete it first and then continue.\n"
                "Section headings must start from ####. Do not output #, ##, or ### headings.\n"
                "Do not output references, external links, URLs, or evidence markers such as [[1]].\n"
                "数学公式：行内 $...$，独立行 $$...$$。\n"
            )
            cont_res = await self._call_llm_response(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a rigorous Markdown continuation assistant. Output only content to append and do not repeat previous content.",
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning=reasoning,
                raise_on_fail=raise_on_fail,
                retries=retries,
            )
            addition = str(cont_res.get("content") or "").strip()
            finish_reason = str(cont_res.get("finish_reason") or "").strip().lower()
            usage = cont_res.get("usage") if isinstance(cont_res.get("usage"), dict) else {}
            if not addition:
                break
            addition = _trim_overlap(content, addition)
            if not addition.strip():
                break
            if not content.endswith("\n") and (
                addition.startswith("####")
                or addition.startswith("- ")
                or addition.startswith("* ")
                or addition.startswith(">")
                or addition.startswith("```")
            ):
                content = content + "\n"
            content = (content + addition).rstrip()
            conts += 1

        if content and _looks_truncated_markdown(content):
            content = _repair_incomplete_markdown(content)

        return {
            "content": content,
            "finish_reason": finish_reason,
            "usage": usage,
            "continuations": conts,
        }

    def _extract_json_obj(self, text: str) -> Dict[str, Any]:
        return extract_first_json_object(text, default={}) or {}

    def _pick_questions(self, questions: List[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
        cleaned: List[Tuple[int, Dict[str, Any]]] = []
        for q in questions:
            stem = str(q.get("stem") or "")
            if not stem or len(stem) < 8:
                continue
            # Prefer fewer images and reasonable length.
            penalty = stem.count("[图片:") * 50 + max(0, len(stem) - 500) // 20
            cleaned.append((penalty, q))
        cleaned.sort(key=lambda x: x[0])
        return [q for _, q in cleaned[: max(1, limit)]]
