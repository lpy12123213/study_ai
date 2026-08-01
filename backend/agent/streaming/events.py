from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any, AsyncIterator, Dict, Optional

from backend.agent.types import (
    ActionResults,
    AgentState,
    CompressedContext,
    PlanStep,
    ReflectionResult,
    StepResult,
    agent_event,
)
from backend.core.logging_utils import get_logger

logger = get_logger(__name__)

def _chunk_text(text: str, *, chunk_size: int = 500) -> AsyncIterator[str]:
    async def _gen() -> AsyncIterator[str]:
        if not text:
            return
        for i in range(0, len(text), chunk_size):
            # Cooperative scheduling so the event loop can flush SSE.
            await asyncio.sleep(0)
            yield text[i : i + chunk_size]

    return _gen()


def _clip_for_sse(value: Any, *, depth: int = 0) -> Any:
    """Best-effort trimming so tool outputs won't overwhelm SSE payloads."""

    if value is None:
        return None

    if isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        max_len = 1200 if depth == 0 else 800
        if len(value) <= max_len:
            return value
        return value[: max_len - 1].rstrip() + "…"

    if isinstance(value, list):
        if depth >= 3:
            return f"[{len(value)} items]"
        max_items = 10 if depth == 0 else 6
        clipped = [_clip_for_sse(x, depth=depth + 1) for x in value[:max_items]]
        if len(value) > max_items:
            clipped.append(f"…（共 {len(value)} 项）")
        return clipped

    if isinstance(value, dict):
        if depth >= 3:
            return "{...}"
        out: Dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            # Common large fields: keep a smaller preview.
            if key in {"markdown", "content", "stem", "solution_markdown"} and isinstance(v, str):
                out[key] = _clip_for_sse(v, depth=depth + 1)
                continue
            out[key] = _clip_for_sse(v, depth=depth + 1)
        return out

    # Fallback: stringify unknown objects (Path, datetime, etc.)
    try:
        return str(value)
    except Exception:
        logger.warning("agent_sse_value_stringify_failed", exc_info=True)
        return "<unserializable>"


class StopStepExecution(Exception):
    """Internal control-flow signal: stop processing the current step after a recovery path succeeded."""


def maybe_capture_markdown_artifact(*, step_result: StepResult, results: ActionResults) -> None:
    if (
        step_result.success
        and step_result.tool in {"assemble_markdown", "revise_markdown"}
        and isinstance(step_result.output, str)
        and step_result.output.strip()
    ):
        results.artifacts["markdown"] = step_result.output.strip()
        return

    if not (step_result.success and isinstance(step_result.output, dict)):
        return

    output = step_result.output
    if step_result.tool in {"assemble_study_archive", "assemble_markdown", "revise_markdown"}:
        markdown = str(output.get("markdown") or output.get("content") or "").strip()
        if markdown:
            results.artifacts["markdown"] = markdown

    if step_result.tool in {"save_markdown_file", "export_study_markdown"}:
        path = str(output.get("path") or "").strip()
        url = str(output.get("url") or output.get("download_url") or "").strip()
        filename = str(output.get("filename") or "").strip()
        if path:
            results.artifacts["markdown_path"] = path
        if url:
            results.artifacts["markdown_url"] = url
        if filename:
            results.artifacts["markdown_filename"] = filename


async def maybe_handle_step_failure(
    *,
    ctx: CompressedContext,
    results: ActionResults,
    concrete_step: PlanStep,
    step_result: StepResult,
    execute_concrete_step: Any,
) -> AsyncIterator[Dict[str, Any]]:
    if step_result.success:
        return

    study_opts = ctx.working_memory.get("study_options")
    study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
    strict_llm = bool(study_opts.get("strict_llm"))

    tool_name = str(step_result.tool or concrete_step.tool or "").strip()
    err = str(step_result.error or "").strip()

    if tool_name == "compile_latex_to_pdf" and not err.startswith("latex_engine_not_found"):
        tex_current = str(ctx.working_memory.get("latex_tex") or "").strip()
        if tex_current:
            ctx.working_memory["_latex_last_compile_error"] = err

        max_rounds = 2
        for i in range(max_rounds):
            if bool(ctx.working_memory.get("_abort_execution")):
                break

            refine_step = PlanStep(
                id=f"auto-refine_latex-{uuid.uuid4().hex[:8]}",
                title=f"自动修复 LaTeX（第 {i + 1} 轮）",
                tool="refine_latex",
                arguments={
                    "topic": ctx.current_task,
                    "subject": str(ctx.user_profile.preferences.get("subject") or "").strip(),
                    "compile_error": err,
                },
                thought="尝试自动修复 LaTeX 编译错误，然后重试编译。",
            )
            async for evt in execute_concrete_step(ctx=ctx, results=results, concrete_step=refine_step):
                yield evt

            compile_step = PlanStep(
                id=f"auto-compile_latex_to_pdf-{uuid.uuid4().hex[:8]}",
                title=f"重试编译 LaTeX（第 {i + 1} 轮）",
                tool="compile_latex_to_pdf",
                arguments={"topic": ctx.current_task},
                thought="重试编译 LaTeX，验证修复是否生效。",
            )
            async for evt in execute_concrete_step(ctx=ctx, results=results, concrete_step=compile_step):
                yield evt

            if results.step_results and results.step_results[-1].success:
                raise StopStepExecution()

    yield agent_event("status", {"content": f"步骤失败：{tool_name}\n错误：{err or 'unknown_error'}"})

    if not tool_name:
        return

    is_llm_error = err.startswith(("llm_", "openai_", "openrouter_"))
    fatal_tools = {
        "split_knowledge_points",
        "review_knowledge_points",
        "generate_outline",
        "assemble_study_archive",
    }
    # generate_study_material 刻意不在 fatal_tools：ReAct 按知识点逐个调用，
    # 单 kp 失败应让其余 kp 与 assemble 继续（空小节会在档案里诚实标注），
    # 而不是整跑中止——此前一次审阅 JSON flake 就会葬送全部已写内容。
    non_fatal_llm_tools = {"refine_latex", "compile_latex_to_pdf"}

    if tool_name in fatal_tools or (strict_llm and is_llm_error and tool_name not in non_fatal_llm_tools):
        ctx.working_memory["_abort_execution"] = True
        ctx.working_memory["_fatal_error"] = {
            "tool": tool_name,
            "step_id": concrete_step.id,
            "error": err or "unknown_error",
        }
        yield agent_event(
            "status",
            {"content": f"关键步骤失败，已停止后续执行：{tool_name}\n错误：{err or 'unknown_error'}"},
        )


async def compress_context(
    *,
    ctx: CompressedContext,
    context_manager: Any,
    set_state: Any,
) -> AsyncIterator[Dict[str, Any]]:
    """Stream a context compression step as tool_call/tool_result events (best-effort)."""

    try:
        set_state(AgentState.COMPRESSING)
    except Exception:
        logger.warning("agent_set_state_failed", extra={"next_state": str(AgentState.COMPRESSING)}, exc_info=True)

    compress_step_id = f"compress_context-{uuid.uuid4().hex[:8]}"
    yield agent_event(
        "tool_call",
        {"step_id": compress_step_id, "name": "compress_context", "title": "压缩上下文", "arguments": {}},
    )

    t0 = time.monotonic()
    try:
        before_tokens = context_manager.estimate_tokens(ctx)
        compress_timeout_s = float(
            os.getenv("STUDY_MATERIALS_COMPRESS_TIMEOUT_S") or os.getenv("AGENT_COMPRESS_TIMEOUT_S") or "12"
        )
        compress_timeout_s = max(2.0, min(compress_timeout_s, 120.0))
        await asyncio.wait_for(context_manager.compress_if_needed(ctx), timeout=compress_timeout_s)
        after_tokens = context_manager.estimate_tokens(ctx)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        yield agent_event(
            "tool_result",
            {
                "step_id": compress_step_id,
                "name": "compress_context",
                "title": "压缩上下文",
                "success": True,
                "elapsed_ms": elapsed_ms,
                "output": {"before_tokens": before_tokens, "after_tokens": after_tokens},
            },
        )
    except Exception as exc:
        logger.warning("agent_context_compress_failed", exc_info=True)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        yield agent_event(
            "tool_result",
            {
                "step_id": compress_step_id,
                "name": "compress_context",
                "title": "压缩上下文",
                "success": False,
                "elapsed_ms": elapsed_ms,
                "error": str(exc),
            },
        )


async def record_session(
    *,
    user_id: str,
    user_input: str,
    reflection: Optional[ReflectionResult],
    memory_store: Any,
) -> AsyncIterator[Dict[str, Any]]:
    """Stream a user-profile update step as tool_call/tool_result events (best-effort)."""

    update_step_id = f"update_user_profile-{uuid.uuid4().hex[:8]}"
    yield agent_event(
        "tool_call",
        {
            "step_id": update_step_id,
            "name": "update_user_profile",
            "title": "更新用户画像",
            "arguments": {
                "user_id": user_id,
                "topic": user_input,
                "passed": bool(reflection.passed) if reflection else True,
            },
        },
    )

    t0 = time.monotonic()
    try:
        profile_timeout_s = float(
            os.getenv("STUDY_MATERIALS_PROFILE_TIMEOUT_S") or os.getenv("AGENT_PROFILE_TIMEOUT_S") or "5"
        )
        profile_timeout_s = max(1.0, min(profile_timeout_s, 60.0))
        await asyncio.wait_for(
            memory_store.record_session(
                user_id=user_id,
                topic=user_input,
                passed=bool(reflection.passed) if reflection else True,
                issues=(reflection.issues if reflection else []),
            ),
            timeout=profile_timeout_s,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        yield agent_event(
            "tool_result",
            {
                "step_id": update_step_id,
                "name": "update_user_profile",
                "title": "更新用户画像",
                "success": True,
                "elapsed_ms": elapsed_ms,
                "output": {
                    "user_id": user_id,
                    "topic": user_input,
                    "passed": bool(reflection.passed) if reflection else True,
                    "issues_count": len((reflection.issues if reflection else []) or []),
                },
            },
        )
    except Exception as exc:
        logger.warning("agent_record_session_failed", exc_info=True)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        yield agent_event(
            "tool_result",
            {
                "step_id": update_step_id,
                "name": "update_user_profile",
                "title": "更新用户画像",
                "success": False,
                "elapsed_ms": elapsed_ms,
                "error": str(exc),
            },
        )
