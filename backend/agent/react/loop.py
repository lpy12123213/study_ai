from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, ValidationError
from pydantic import Field as PydanticField

from backend.agent.config import AgentConfig
from backend.agent.mcp.registry import MCPToolRegistry
from backend.agent.react.prompts import build_react_messages
from backend.agent.types import ActionResults, CompressedContext, ExecutionPlan, PlanStep, agent_event
from backend.core.logging_utils import get_logger
from backend.core.text_utils import clip_text as _clip_text
from backend.llm.client import chat_completion, is_llm_configured
from backend.llm.json_utils import extract_first_json_object

logger = get_logger(__name__)


def _extract_first_json_object(text: str) -> Dict[str, Any]:
    return extract_first_json_object(text, default={}) or {}


class ReActDecisionPayload(BaseModel):
    thought: str = ""
    action: str = ""
    batch_mode: str = ""
    arguments: Dict[str, Any] = PydanticField(default_factory=dict)
    note: str = ""


REACT_DECISION_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "react_decision",
        "description": "Return the next ReAct controller decision.",
        "parameters": {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "action": {"type": "string"},
                "batch_mode": {"type": "string"},
                "arguments": {"type": "object", "additionalProperties": True},
                "note": {"type": "string"},
            },
            "required": ["thought", "action", "arguments"],
            "additionalProperties": False,
        },
    },
}

REACT_DECISION_TOOL_CHOICE: Dict[str, Any] = {
    "type": "function",
    "function": {"name": "react_decision"},
}


def _dump_pydantic_model(model: BaseModel) -> Dict[str, Any]:
    dump = getattr(model, "model_dump", None)
    if callable(dump):
        return dict(dump())
    return dict(model.dict())


def _validate_decision_payload(obj: Any) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        return {}

    try:
        validate = getattr(ReActDecisionPayload, "model_validate", None)
        if callable(validate):
            payload = validate(obj)
        else:
            payload = ReActDecisionPayload.parse_obj(obj)
    except (TypeError, ValueError, ValidationError):
        return {}

    data = _dump_pydantic_model(payload)
    if not str(data.get("action") or "").strip():
        return {}
    if not isinstance(data.get("arguments"), dict):
        return {}
    return data


def _extract_tool_decision(res: Any) -> Dict[str, Any]:
    tool_calls = getattr(res, "tool_calls", None)
    if not isinstance(tool_calls, list):
        return {}

    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = str(fn.get("name") or call.get("name") or "").strip()
        if name != "react_decision":
            continue

        raw_args = fn.get("arguments", call.get("arguments"))
        if isinstance(raw_args, dict):
            args_obj = raw_args
        else:
            args_obj = _extract_first_json_object(str(raw_args or ""))
        return _validate_decision_payload(args_obj)

    return {}


def _normalize_key(text: str) -> str:
    return str(text or "").strip().lower().replace("-", "").replace("_", "")


def _get_split_knowledge_points(ctx: CompressedContext) -> List[str]:
    wm = ctx.working_memory if isinstance(ctx.working_memory, dict) else {}
    split_res = wm.get("split_knowledge_points")
    if not (isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list)):
        return []
    kps = [str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()]
    return kps[:15]


def _extract_primary_kp(arguments: Dict[str, Any]) -> str:
    if not isinstance(arguments, dict):
        return ""

    kp = str(arguments.get("knowledge_point") or "").strip()
    if kp:
        return kp

    kps = arguments.get("knowledge_points")
    if isinstance(kps, list) and len(kps) == 1:
        return str(kps[0] or "").strip()
    return ""


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _assess_tool_result(
    *,
    tool: str,
    success: bool,
    output: Any,
    error: str,
    arguments: Dict[str, Any],
) -> Tuple[str, str]:
    """Best-effort tool quality assessment for ReAct gating.

    Returns: (rating, reason) where rating in {HIGH, MEDIUM, LOW, FAILED}.
    """

    tool = str(tool or "").strip()
    if not success:
        return "FAILED", _clip_text(str(error or "").strip() or "tool_failed", max_chars=140)

    norm = _normalize_key(tool)
    if norm == "websearchknowledge":
        limit = 0
        if isinstance(arguments, dict):
            limit = _safe_int(arguments.get("limit"))
        if not limit and isinstance(output, dict):
            limit = _safe_int(output.get("limit"))
        if limit <= 0:
            limit = 10

        kps = []
        if isinstance(arguments, dict) and isinstance(arguments.get("knowledge_points"), list):
            kps = [str(x or "").strip() for x in (arguments.get("knowledge_points") or []) if str(x or "").strip()]
        expected = limit * (len(kps) if kps else 1)

        returned = 0
        if isinstance(output, dict) and isinstance(output.get("items"), list):
            for it in [x for x in (output.get("items") or []) if isinstance(x, dict)]:
                results = it.get("results") if isinstance(it.get("results"), list) else []
                returned += len([x for x in results if x])

        if expected <= 0:
            expected = max(1, returned)
        ratio = (returned / expected) if expected else 0.0
        reason = f"{returned}/{expected} results returned"
        if ratio < 0.5:
            return "LOW", reason
        if ratio >= 0.9:
            return "HIGH", reason
        return "MEDIUM", reason

    if norm == "generatestudymaterial":
        sections = []
        if isinstance(output, dict) and isinstance(output.get("sections"), list):
            sections = [x for x in (output.get("sections") or []) if isinstance(x, dict)]

        expected = 0
        if isinstance(arguments, dict) and isinstance(arguments.get("knowledge_points"), list):
            expected = len([x for x in (arguments.get("knowledge_points") or []) if str(x or "").strip()])
        expected = expected or len(sections) or 1

        content_lens: List[int] = []
        for s in sections:
            md = str(s.get("explanation_markdown") or "").strip()
            if md:
                content_lens.append(len(md))
        avg_chars = int(sum(content_lens) / len(content_lens)) if content_lens else 0

        ratio = (len(sections) / expected) if expected else 0.0
        reason = f"sections={len(sections)}/{expected}, avg_chars≈{avg_chars}"
        if len(sections) <= 0 or avg_chars < 220:
            return "LOW", reason
        if ratio >= 0.9 and avg_chars >= 900:
            return "HIGH", reason
        return "MEDIUM", reason

    if norm == "aggregateknowledge":
        # Prefer a dedicated `facts` field if present; otherwise approximate by counting non-empty signals.
        facts_total = 0
        if isinstance(output, dict) and isinstance(output.get("facts"), list):
            facts_total = len(
                [
                    x
                    for x in (output.get("facts") or [])
                    if isinstance(x, dict) and str(x.get("fact") or "").strip()
                ]
            )
        if facts_total <= 0 and isinstance(output, dict) and isinstance(output.get("items"), list):
            items = [x for x in (output.get("items") or []) if isinstance(x, dict)]
            for it in items:
                wiki = it.get("wikipedia") if isinstance(it.get("wikipedia"), dict) else {}
                mw = it.get("mediawiki") if isinstance(it.get("mediawiki"), dict) else {}
                if str(wiki.get("summary") or wiki.get("content") or "").strip():
                    facts_total += 1
                if str(mw.get("summary") or mw.get("content") or "").strip():
                    facts_total += 1

                for blob_key, list_key in (
                    ("web_search", "results"),
                    ("web_pages", "pages"),
                    ("github", "results"),
                    ("stackexchange", "results"),
                ):
                    blob = it.get(blob_key) if isinstance(it.get(blob_key), dict) else {}
                    lst = blob.get(list_key) if isinstance(blob.get(list_key), list) else []
                    facts_total += len([x for x in lst if x])

                q = it.get("questions") if isinstance(it.get("questions"), dict) else {}
                for k in ("questions", "examples", "exercises"):
                    lst = q.get(k) if isinstance(q.get(k), list) else []
                    facts_total += len([x for x in lst if x])

        kp_n = 0
        if isinstance(output, dict) and isinstance(output.get("knowledge_points"), list):
            kp_n = len([x for x in (output.get("knowledge_points") or []) if str(x or "").strip()])
        kp_n = kp_n or (
            len(output.get("items") or []) if isinstance(output, dict) and isinstance(output.get("items"), list) else 0
        )
        kp_n = kp_n or 1

        reason = f"facts≈{facts_total} across {kp_n} KP"
        if facts_total <= 0:
            return "LOW", reason
        if facts_total >= kp_n * 3:
            return "HIGH", reason
        return "MEDIUM", reason

    if norm == "reviewcontent":
        passed = None
        if isinstance(output, dict):
            passed = output.get("passed")
        if isinstance(passed, bool):
            if passed:
                return "HIGH", "passed"
            issues = output.get("issues") if isinstance(output, dict) else None
            issues_list = issues if isinstance(issues, list) else []
            first = str(issues_list[0] or "").strip() if issues_list else ""
            return "LOW", _clip_text(first or "review_failed", max_chars=140)
        return "MEDIUM", "no_passed_flag"

    # Default: binary success signal.
    return "HIGH", "success"


def _aggregate_quality(qualities: List[Tuple[str, str]]) -> Tuple[str, str]:
    if not qualities:
        return "MEDIUM", "no_results"

    counts: Dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "FAILED": 0}
    for q, _r in qualities:
        qn = str(q or "").strip().upper()
        if qn not in counts:
            qn = "MEDIUM"
        counts[qn] += 1

    if counts["FAILED"] > 0:
        rating = "FAILED"
    elif counts["LOW"] > 0:
        rating = "LOW"
    elif counts["MEDIUM"] > 0:
        rating = "MEDIUM"
    else:
        rating = "HIGH"

    # Keep the reason compact; scratchpad already contains per-step details when needed.
    if sum(counts.values()) <= 1:
        return rating, qualities[0][1] if qualities else ""

    reason = f"HIGH={counts['HIGH']}, MEDIUM={counts['MEDIUM']}, LOW={counts['LOW']}, FAILED={counts['FAILED']}"
    return rating, reason


def _split_quality_and_observation(observation: str) -> Tuple[str, str]:
    raw = str(observation or "").strip()
    if not raw:
        return "Quality: MEDIUM (empty_observation)", ""
    lines = raw.splitlines()
    if lines and lines[0].strip().lower().startswith("quality:"):
        q_line = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        return q_line, body
    return "Quality: MEDIUM (no_quality_line)", raw


def _format_tool_output_preview(tool: str, output: Any) -> str:
    tool_name = str(tool or "").strip()

    if tool_name == "generate_study_material" and isinstance(output, dict):
        sections = output.get("sections") if isinstance(output.get("sections"), list) else []
        kps: List[str] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            kp = str(section.get("knowledge_point") or "").strip()
            if kp:
                kps.append(kp)
        compact = {
            "success": bool(output.get("success", True)),
            "sections_count": len(sections),
            "knowledge_points": kps[:8],
            "markdown_chars": len(str(output.get("markdown") or output.get("content") or "")),
        }
        return json.dumps(compact, ensure_ascii=False)

    try:
        raw = json.dumps(output, ensure_ascii=False)
    except (TypeError, ValueError):
        raw = str(output)

    longer_preview_tools = {
        "web_search_knowledge",
        "github_search",
        "stackexchange_search",
        "mediawiki_search",
        "browse_web_pages",
        "wikipedia_search",
        "aggregate_knowledge",
        "synthesize_sources",
    }
    code_preview_tools = {
        "convert_markdown_to_latex",
        "refine_latex",
        "compile_latex_to_pdf",
        "draw_svg_diagram",
        "render_tikz_diagram",
        "render_asy_diagram",
        "plot_data",
    }
    max_chars = 600 if tool_name in longer_preview_tools else 480 if tool_name in code_preview_tools else 260
    return _clip_text(raw, max_chars=max_chars)


def _format_observation(
    step_results: List[Any],
    *,
    quality: str,
    reason: str,
    step_args_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    q = str(quality or "").strip().upper() or "MEDIUM"
    r = str(reason or "").strip()
    head = f"Quality: {q}" + (f" ({r})" if r else "")

    lines: List[str] = [head]
    for r in step_results or []:
        tool = str(getattr(r, "tool", "") or "").strip()
        ok = bool(getattr(r, "success", False))
        err = str(getattr(r, "error", "") or "").strip()
        out = getattr(r, "output", None)
        out_preview = ""
        if out is not None:
            out_preview = _format_tool_output_preview(tool, out)

        tool_label = tool
        if step_args_by_id:
            step_id = str(getattr(r, "step_id", "") or "").strip()
            args = step_args_by_id.get(step_id) if step_id else None
            kp = _extract_primary_kp(args or {})
            if kp:
                tool_label = f"{tool}({kp})"

        if ok:
            if out_preview:
                lines.append(f"- {tool_label}: ok; output={out_preview}")
            else:
                lines.append(f"- {tool_label}: ok")
        else:
            lines.append(f"- {tool_label}: failed; error={_clip_text(err, max_chars=220) or 'unknown_error'}")
        if len(lines) >= 6:
            lines.append("- ...")
            break
    return "\n".join(lines).strip()


@dataclass
class ReActDecision:
    thought: str = ""
    action: str = ""
    batch_mode: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    note: str = ""


Decider = Callable[[List[Dict[str, str]]], Awaitable[Dict[str, Any]]]
ExecuteStep = Callable[[PlanStep], AsyncIterator[Dict[str, Any]]]
ExecuteBatch = Callable[[List[PlanStep]], AsyncIterator[Dict[str, Any]]]


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

    async def _json_decide(
        self,
        *,
        messages: List[Dict[str, str]],
        model: str,
        max_tokens: int,
        repair_reason: str = "",
    ) -> Dict[str, Any]:
        json_messages = list(messages)
        if repair_reason:
            json_messages.append(
                {
                    "role": "user",
                    "content": (
                        "The previous ReAct decision was invalid: "
                        f"{_clip_text(repair_reason, max_chars=240)}. "
                        "Return only one JSON object with string fields thought/action/batch_mode/note "
                        "and an object field arguments."
                    ),
                }
            )
        try:
            res = await chat_completion(
                messages=json_messages,
                model=model,
                temperature=0.2,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                stream=False,
                retries=3,
                req_id_prefix="react",
            )
        except Exception:
            logger.warning("react_llm_decide_failed", exc_info=True)
            return {}

        raw = str(getattr(res, "content", "") or "")
        obj = _extract_first_json_object(raw)
        decision = _validate_decision_payload(obj)
        if decision:
            return decision

        if repair_reason:
            return {}

        repair_messages = list(messages)
        if raw.strip():
            repair_messages.append({"role": "assistant", "content": raw})
        return await self._json_decide(
            messages=repair_messages,
            model=model,
            max_tokens=max_tokens,
            repair_reason="missing or malformed JSON decision",
        )

    async def _llm_decide(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        model = str(self.config.planner_model or "").strip()
        if not model or not is_llm_configured():
            return {}

        max_tokens = 900

        try:
            res = await chat_completion(
                messages=messages,
                model=model,
                temperature=0.2,
                max_tokens=max_tokens,
                tools=[REACT_DECISION_TOOL],
                tool_choice=REACT_DECISION_TOOL_CHOICE,
                stream=False,
                retries=3,
                req_id_prefix="react",
            )
            decision = _extract_tool_decision(res)
            if decision:
                return decision
        except Exception:
            logger.warning("react_llm_tool_decide_failed", exc_info=True)

        return await self._json_decide(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            repair_reason="missing or invalid react_decision tool call",
        )

    async def _decide(self, messages: List[Dict[str, str]]) -> ReActDecision:
        if self._decide_next is not None:
            obj = await self._decide_next(messages)
        else:
            obj = await self._llm_decide(messages)

        if not isinstance(obj, dict):
            obj = {}

        thought = str(obj.get("thought") or "").strip()
        action = str(obj.get("action") or "").strip()
        batch_mode = str(obj.get("batch_mode") or "").strip()
        note = str(obj.get("note") or "").strip()
        args = obj.get("arguments")
        arguments = dict(args) if isinstance(args, dict) else {}
        return ReActDecision(thought=thought, action=action, batch_mode=batch_mode, arguments=arguments, note=note)

    def _tool_exists(self, name: str) -> bool:
        try:
            return self.tool_registry.get_tool(name) is not None
        except Exception:
            logger.warning("react_tool_registry_lookup_failed", extra={"tool": name}, exc_info=True)
            return False

    async def run(
        self,
        *,
        ctx: CompressedContext,
        results: ActionResults,
        topic: str,
        subject: str,
        execute_concrete_step: ExecuteStep,
        execute_step_block: Optional[ExecuteBatch] = None,
        max_iterations: int,
        skip_export: bool,
    ) -> AsyncIterator[Dict[str, Any]]:
        max_iterations = int(max_iterations or 0)
        if max_iterations <= 0:
            max_iterations = int(self.config.react_max_iterations or 20)
        max_iterations = max(1, min(max_iterations, 60))

        tools = self.tool_registry.list_tools()

        scratch: List[Dict[str, Any]] = []

        llm_call_budget = int(getattr(self.config, "react_llm_call_budget", 25) or 25)
        # Scale LLM call budget by preset so research mode actually researches.
        try:
            opts_for_preset = ctx.working_memory.get("study_options") if isinstance(ctx.working_memory, dict) else {}
            preset_for_budget = ""
            if isinstance(opts_for_preset, dict):
                preset_for_budget = str(opts_for_preset.get("preset") or "").strip().lower()
        except (AttributeError, TypeError):
            preset_for_budget = ""
        preset_llm_floor = {"quick": 8, "standard": 18, "deep": 32, "research": 45}
        if preset_for_budget in preset_llm_floor:
            llm_call_budget = max(llm_call_budget, preset_llm_floor[preset_for_budget])
        llm_call_budget = max(1, min(llm_call_budget, 200))
        llm_calls = 0

        retry_budget_per_tool = int(getattr(self.config, "react_retry_budget_per_tool", 2) or 2)
        retry_budget_per_tool = max(0, min(retry_budget_per_tool, 10))
        attempt_tracker: Dict[Tuple[str, str], int] = {}
        injected_checkpoints: set[str] = set()

        def _retry_exceeded_system_note() -> str:
            if retry_budget_per_tool <= 0:
                return ""
            exceeded = [
                (tool_name, kp, max(0, attempts - 1))
                for (tool_name, kp), attempts in attempt_tracker.items()
                if tool_name and kp and max(0, attempts - 1) >= retry_budget_per_tool
            ]
            if not exceeded:
                return ""
            exceeded.sort(key=lambda x: x[2], reverse=True)
            lines = [
                "重试限制提醒：以下工具/知识点组合已超过重试上限，请更换策略或跳过该 KP（避免无限重试）：",
            ]
            for tool_name, kp, n in exceeded[:4]:
                lines.append(f"- {tool_name} @ {kp}: {n} 次（上限 {retry_budget_per_tool}）")
            return "\n".join(lines).strip()

        def _should_inject_checkpoint(*, last_action: str) -> Optional[Dict[str, Any]]:
            wm = ctx.working_memory if isinstance(ctx.working_memory, dict) else {}

            # (1) review_content failed -> inject issues immediately.
            if str(last_action or "").strip() == "review_content":
                review = wm.get("review_content")
                if isinstance(review, dict) and review.get("passed") is False:
                    issues = review.get("issues") if isinstance(review.get("issues"), list) else []
                    issues = [str(x or "").strip() for x in issues if str(x or "").strip()]
                    sig = "review_failed:" + "|".join(issues[:6])
                    if sig not in injected_checkpoints:
                        injected_checkpoints.add(sig)
                        msg = "review_content 未通过。建议优先修复以下问题后再继续：\n"
                        if issues:
                            msg += "\n".join(f"- {x}" for x in issues[:6])
                        else:
                            msg += "- （未提供 issues）建议补充来源/修正结构后重试 review_content。"
                        return {
                            "thought": "Checkpoint: review_content 未通过，需要迭代修正。",
                            "action": "checkpoint",
                            "observation": f"Quality: LOW (review_failed)\n{_clip_text(msg, max_chars=800)}",
                        }

            # (2) all KPs have study material -> prompt review.
            if "all_material_generated" not in injected_checkpoints:
                kps = _get_split_knowledge_points(ctx)
                if kps:
                    gen = wm.get("generate_study_material") or wm.get("study_material") or {}
                    done_kps: set[str] = set()
                    if isinstance(gen, dict) and isinstance(gen.get("sections"), list):
                        for s in gen.get("sections") or []:
                            if not isinstance(s, dict):
                                continue
                            kp = str(s.get("knowledge_point") or "").strip()
                            md = str(s.get("explanation_markdown") or "").strip()
                            if kp and md:
                                done_kps.add(kp)
                    if len(done_kps) >= len(kps) and not isinstance(wm.get("review_content"), dict):
                        injected_checkpoints.add("all_material_generated")
                        return {
                            "thought": "Checkpoint: 材料已覆盖全部知识点。",
                            "action": "checkpoint",
                            "observation": (
                                "Quality: MEDIUM (ready_for_review)\n"
                                "- 所有知识点的 generate_study_material 已完成：建议现在调用 review_content 做审查；若未通过，根据 issues 补检索/修订。"
                            ),
                        }

            # (3) budget threshold reached -> prompt wrap-up.
            # Research mode is given more headroom (90%) so it has time to do additional retrieval rounds.
            wrap_up_ratio = 0.90 if preset_for_budget == "research" else (0.85 if preset_for_budget == "deep" else 0.75)
            if "budget_threshold" not in injected_checkpoints and llm_call_budget > 0:
                used_ratio = llm_calls / llm_call_budget
                if used_ratio >= wrap_up_ratio:
                    injected_checkpoints.add("budget_threshold")
                    remaining = max(0, llm_call_budget - llm_calls)
                    return {
                        "thought": "Checkpoint: 决策预算接近用尽，建议收尾。",
                        "action": "checkpoint",
                        "observation": (
                            "Quality: MEDIUM (budget_warning)\n"
                            f"- 剩余 LLM 决策预算：{remaining}/{llm_call_budget}。建议优先："
                            "assemble_study_archive → save/export → review_content。"
                        ),
                    }

            return None

        yield agent_event("status", {"content": f"ReAct 模式：动态调用工具（最多 {max_iterations} 轮）…"})

        for i in range(max_iterations):
            if bool(ctx.working_memory.get("_abort_execution")):
                break
            if llm_calls >= llm_call_budget:
                yield agent_event("status", {"content": "ReAct：LLM 决策预算已用尽，进入收尾（deterministic finalization）…"})
                break

            scratch_lines: List[str] = []
            for idx, x in enumerate(scratch[-8:]):
                if not isinstance(x, dict):
                    continue
                q_line, body = _split_quality_and_observation(str(x.get("observation") or ""))
                scratch_lines.append(
                    f"{idx + 1}. Thought: {_clip_text(str(x.get('thought') or ''), max_chars=120)}\n"
                    f"   Action: {x.get('action')}\n"
                    f"   {_clip_text(q_line, max_chars=160)}\n"
                    f"   Observation: {_clip_text(body, max_chars=180)}"
                )
            scratchpad_text = "\n".join(scratch_lines).strip()

            messages = build_react_messages(
                ctx=ctx,
                topic=topic,
                subject=subject,
                tools=tools,
                scratchpad=scratchpad_text,
                iteration=i,
                max_iterations=max_iterations,
                budget_remaining=max(0, llm_call_budget - llm_calls),
            )

            retry_note = _retry_exceeded_system_note()
            if retry_note:
                messages.insert(1, {"role": "system", "content": retry_note})

            llm_calls += 1
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
                        "observation": "Quality: FAILED (empty_action)\n- empty_action",
                    }
                )
                yield agent_event("status", {"content": "ReAct：未返回 action，已跳过本轮。"})
                continue

            # Inline knowledge-point splitting. The controller LLM provides the KP list
            # directly in `arguments.knowledge_points` so we don't pay an extra
            # split_knowledge_points tool round-trip. This is consumed by the same
            # downstream code that reads ctx.working_memory["split_knowledge_points"].
            if action_norm in {"setknowledgepoints", "splitknowledgepointsinline", "providekps", "kpsinline"}:
                args_obj = decision.arguments if isinstance(decision.arguments, dict) else {}
                raw_kps = args_obj.get("knowledge_points") if isinstance(args_obj.get("knowledge_points"), list) else []
                cleaned: List[str] = []
                seen: set = set()
                for it in raw_kps or []:
                    s = str(it or "").strip()
                    if not s or s in seen:
                        continue
                    seen.add(s)
                    cleaned.append(s)
                    if len(cleaned) >= 15:
                        break
                if cleaned:
                    ctx.working_memory["split_knowledge_points"] = {
                        "topic": str(args_obj.get("topic") or topic or "").strip(),
                        "subject": str(args_obj.get("subject") or subject or "").strip(),
                        "knowledge_points": cleaned,
                        "source": "controller_inline",
                    }
                    obs = (
                        "Quality: HIGH (inline_split_ok)\n"
                        f"- 已记录 {len(cleaned)} 个知识点（由主 agent 直接提供，未消耗 tool 预算）：\n"
                        f"  {', '.join(cleaned[:8])}{'...' if len(cleaned) > 8 else ''}"
                    )
                    yield agent_event(
                        "status",
                        {"content": f"已直接采纳主 agent 提供的 {len(cleaned)} 个知识点。"},
                    )
                else:
                    obs = (
                        "Quality: FAILED (empty_kps)\n"
                        "- arguments.knowledge_points 为空或格式错误"
                    )
                scratch.append(
                    {
                        "thought": decision.thought,
                        "action": action,
                        "arguments": decision.arguments,
                        "observation": obs,
                    }
                )
                continue

            if not self._tool_exists(action):
                scratch.append(
                    {
                        "thought": decision.thought,
                        "action": action,
                        "observation": f"Quality: FAILED (tool_not_found)\n- tool_not_found: {action}",
                    }
                )
                yield agent_event("status", {"content": f"ReAct：未知工具 {action}，请更换 action。"})
                continue

            batch_mode_norm = _normalize_key(decision.batch_mode)
            use_batch_per_kp = (
                batch_mode_norm in {"perknowledgepoint", "perk", "perkps", "perkp"}
                or decision.batch_mode == "per_knowledge_point"
            )
            if use_batch_per_kp and execute_step_block is not None:
                kps = _get_split_knowledge_points(ctx)
                if (
                    not kps
                    and isinstance(decision.arguments, dict)
                    and isinstance(decision.arguments.get("knowledge_points"), list)
                ):
                    kps = [
                        str(x or "").strip()
                        for x in (decision.arguments.get("knowledge_points") or [])
                        if str(x or "").strip()
                    ][:15]
                if not kps:
                    kps = [topic] if topic else []

                if len(kps) <= 1:
                    use_batch_per_kp = False
                else:
                    pg = f"react-batch-{i + 1}-{uuid.uuid4().hex[:6]}"
                    steps: List[PlanStep] = []
                    for kp in kps:
                        args = dict(decision.arguments or {})
                        if "knowledge_point" in args:
                            args["knowledge_point"] = kp
                        else:
                            args["knowledge_points"] = [kp]

                        steps.append(
                            PlanStep(
                                id=f"react-batch-{i + 1}-{uuid.uuid4().hex[:8]}",
                                title=f"ReAct(batch): {action} · {kp}",
                                tool=action,
                                arguments=args,
                                parallel_group=pg,
                                thought="",
                            )
                        )

                    yield agent_event(
                        "status",
                        {"content": f"ReAct：批量执行 {action}（per_knowledge_point，{len(steps)} 个）…"},
                    )
                    before_n = len(results.step_results)
                    async for evt in execute_step_block(steps):
                        yield evt
                    after = results.step_results[before_n:]

                    step_args_by_id = {s.id: s.arguments for s in steps}
                    qualities = [
                        _assess_tool_result(
                            tool=str(getattr(r, "tool", "") or action),
                            success=bool(getattr(r, "success", False)),
                            output=getattr(r, "output", None),
                            error=str(getattr(r, "error", "") or ""),
                            arguments=step_args_by_id.get(str(getattr(r, "step_id", "") or ""), {}),
                        )
                        for r in after
                    ]
                    q_rating, q_reason = _aggregate_quality(qualities)
                    observation = _format_observation(
                        after,
                        quality=q_rating,
                        reason=q_reason,
                        step_args_by_id=step_args_by_id,
                    )

                    # Retry tracking per KP for batch mode.
                    if retry_budget_per_tool > 0:
                        for s in steps:
                            kp = _extract_primary_kp(s.arguments)
                            if not kp:
                                continue
                            key = (action, kp)
                            attempt_tracker[key] = int(attempt_tracker.get(key) or 0) + 1

                    scratch.append(
                        {
                            "thought": decision.thought,
                            "action": f"{action} (batch per_knowledge_point)",
                            "arguments": decision.arguments,
                            "observation": observation,
                        }
                    )

                    checkpoint = _should_inject_checkpoint(last_action=action)
                    if checkpoint:
                        scratch.append(checkpoint)
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

            step_args_by_id = {step.id: step.arguments}
            step_result = after[0] if after else None
            q_rating, q_reason = _assess_tool_result(
                tool=str(getattr(step_result, "tool", "") or action),
                success=bool(getattr(step_result, "success", False)),
                output=getattr(step_result, "output", None),
                error=str(getattr(step_result, "error", "") or ""),
                arguments=step.arguments,
            )
            observation = _format_observation(after, quality=q_rating, reason=q_reason, step_args_by_id=step_args_by_id)

            # Retry tracking per KP (only when kp is unambiguous).
            if retry_budget_per_tool > 0:
                kp = _extract_primary_kp(step.arguments)
                if kp:
                    key = (action, kp)
                    attempt_tracker[key] = int(attempt_tracker.get(key) or 0) + 1

            scratch.append(
                {
                    "thought": decision.thought,
                    "action": action,
                    "arguments": decision.arguments,
                    "observation": observation,
                }
            )

            checkpoint = _should_inject_checkpoint(last_action=action)
            if checkpoint:
                scratch.append(checkpoint)

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
            isinstance(ctx.working_memory.get("markdown"), str)
            and str(ctx.working_memory.get("markdown") or "").strip()
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
