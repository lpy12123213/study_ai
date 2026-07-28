from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, Optional

from backend.core.settings import env_int
from backend.core.text_utils import clip_text
from backend.generation.agentic.codex_runtime import run_codex_runtime_agent_events
from backend.generation.agentic.study_materials import build_study_materials_agent_spec

STAGE_VERSION = 1
# 阶段提示词载荷预算默认值（env STUDY_MATERIALS_STAGE_PROMPT_MAX_CHARS 可调）。
_STAGE_PROMPT_DEFAULT_MAX_CHARS = 30000
_RESEARCH_ITEMS_PER_KP = 4
_RESEARCH_SNIPPET_MAX_CHARS = 500
STAGE_RESULT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "summary", "result"],
    "properties": {
        "status": {"type": "string", "enum": ["completed", "failed"]},
        "summary": {"type": "string"},
        "result": {
            "type": "object",
            "additionalProperties": False,
            "required": ["stage", "stage_status", "stage_version", "payload"],
            "properties": {
                "stage": {"type": "string", "enum": ["plan", "draft", "revise"]},
                "stage_status": {"type": "string", "enum": ["completed"]},
                "stage_version": {"type": "integer", "enum": [STAGE_VERSION]},
                "payload": {"type": "object", "additionalProperties": True},
            },
        },
    },
}

StageEventSink = Callable[[Dict[str, Any]], Awaitable[None]]


class StageResultError(RuntimeError):
    def __init__(self, code: str, *, stage: str = "", detail: str = "") -> None:
        self.code = str(code or "invalid_stage_result")
        self.stage = str(stage or "")
        self.detail = str(detail or "")
        super().__init__(f"{self.code}: {self.stage}{(': ' + self.detail) if self.detail else ''}")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_plan_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_points = payload.get("knowledge_points") if isinstance(payload.get("knowledge_points"), list) else []
    points: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_points):
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title") or item.get("knowledge_point"))
        point_id = _text(item.get("id")) or f"kp-{index + 1}"
        queries_raw = item.get("queries") if isinstance(item.get("queries"), list) else []
        queries = [_text(query) for query in queries_raw if _text(query)]
        if not title or point_id in seen or not queries:
            continue
        seen.add(point_id)
        points.append({"id": point_id, "title": title, "queries": list(dict.fromkeys(queries))[:6]})
    if not points:
        raise StageResultError("invalid_stage_result", stage="plan", detail="knowledge_points_missing")
    dimensions = payload.get("content_dimensions") if isinstance(payload.get("content_dimensions"), list) else []
    return {
        **payload,
        "knowledge_points": points,
        "content_dimensions": [_text(item) for item in dimensions if _text(item)],
    }


def _normalize_markdown_payload(stage: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    markdown = _text(payload.get("markdown"))
    coverage = payload.get("coverage_map") if isinstance(payload.get("coverage_map"), dict) else None
    if not markdown or coverage is None:
        raise StageResultError("invalid_stage_result", stage=stage, detail="markdown_or_coverage_missing")
    return {**payload, "markdown": markdown, "coverage_map": dict(coverage)}


def normalize_stage_result(expected_stage: str, result: Dict[str, Any]) -> Dict[str, Any]:
    stage = _text(result.get("stage")) if isinstance(result, dict) else ""
    status = _text(result.get("stage_status")) if isinstance(result, dict) else ""
    payload = result.get("payload") if isinstance(result, dict) and isinstance(result.get("payload"), dict) else None
    try:
        version = int(result.get("stage_version") or 0) if isinstance(result, dict) else 0
    except (TypeError, ValueError):
        version = 0
    if stage != _text(expected_stage) or status != "completed" or version != STAGE_VERSION or payload is None:
        raise StageResultError("invalid_stage_result", stage=expected_stage, detail="stage_contract_mismatch")
    if stage == "plan":
        return _normalize_plan_payload(payload)
    if stage in {"draft", "revise"}:
        return _normalize_markdown_payload(stage, payload)
    raise StageResultError("invalid_stage_result", stage=expected_stage, detail="unsupported_stage")


def _slim_research_payload(research: Any) -> Any:
    """Trim research evidence to the top items per knowledge point for prompt size."""

    if not isinstance(research, dict):
        return research
    slimmed: Dict[str, Any] = {}
    for key, items in research.items():
        if not isinstance(items, list):
            slimmed[key] = items
            continue
        trimmed: list[Any] = []
        for item in items[:_RESEARCH_ITEMS_PER_KP]:
            if isinstance(item, dict):
                trimmed.append({**item, "snippet": clip_text(item.get("snippet"), _RESEARCH_SNIPPET_MAX_CHARS)})
            else:
                trimmed.append(item)
        slimmed[key] = trimmed
    return slimmed


def _cap_stage_input(stage_input: Dict[str, Any], *, stage: str, max_chars: int) -> Dict[str, Any]:
    """Pre-truncate payload fields so the serialized stage input stays within budget.

    draft/revise 都内联 plan+research（revise 还带完整 markdown），需要统一瘦身；
    plan 载荷本身很小，不处理。
    """

    if stage not in {"draft", "revise"} or max_chars <= 0:
        return stage_input
    payload = stage_input.get("input")
    if not isinstance(payload, dict):
        return stage_input
    capped = dict(payload)
    if "research" in capped:
        capped["research"] = _slim_research_payload(capped.get("research"))
    markdown = capped.get("markdown")
    if isinstance(markdown, str) and markdown:
        # 用“其余字段序列化后的剩余预算”截断正文，保证整个阶段输入不超限。
        base = json.dumps(
            {**stage_input, "input": {key: value for key, value in capped.items() if key != "markdown"}},
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        budget = max(0, max_chars - len(base) - 16)
        capped["markdown"] = clip_text(markdown, budget)
    return {**stage_input, "input": capped}


def build_stage_prompt(
    *,
    stage: str,
    topic: str,
    subject: str,
    preset: str,
    options: Optional[Dict[str, Any]] = None,
    payload: Dict[str, Any],
) -> str:
    stage_instruction = {
        "plan": (
            "把主题拆成可教学、互不重复的知识点，并为每个知识点给出至少一个可执行检索查询。"
            "返回 payload.knowledge_points=[{id,title,queries}] 和 payload.content_dimensions。"
        ),
        "draft": (
            "仅依据输入中的已验证研究证据撰写完整 Markdown；覆盖每个知识点，并返回 "
            "payload.markdown 与 payload.coverage_map。不要声称整个任务已经完成。"
        ),
        "revise": (
            "根据输入中的审查问题定向修订完整 Markdown，保留可靠内容和来源说明；返回 "
            "payload.markdown、payload.coverage_map 与 payload.resolved_issues。"
        ),
    }.get(stage)
    if not stage_instruction:
        raise StageResultError("invalid_stage_result", stage=stage, detail="unsupported_stage")
    max_chars = max(0, env_int("STUDY_MATERIALS_STAGE_PROMPT_MAX_CHARS", _STAGE_PROMPT_DEFAULT_MAX_CHARS))
    stage_input_obj = _cap_stage_input(
        {
            "topic": _text(topic),
            "subject": _text(subject),
            "preset": _text(preset) or "standard",
            "options": dict(options or {}),
            "stage": stage,
            "input": payload,
        },
        stage=stage,
        max_chars=max_chars,
    )
    stage_input = json.dumps(
        stage_input_obj,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return (
        "你是 Study AI 自学资料工作流中的单阶段 Codex worker。\n"
        f"当前阶段：{stage}。{stage_instruction}\n"
        "你无权完成整个任务；顶层 status=completed 只表示本阶段成功。\n"
        "只返回一个 JSON 对象："
        '{"status":"completed","summary":"...","result":'
        f'{{"stage":"{stage}","stage_status":"completed","stage_version":{STAGE_VERSION},"payload":{{}}}}}}。\n'
        f"阶段输入：{stage_input}"
    )


async def run_codex_stage(
    *,
    stage: str,
    task_id: str,
    user_id: str,
    topic: str,
    subject: str,
    preset: str,
    options: Optional[Dict[str, Any]] = None,
    payload: Dict[str, Any],
    event_sink: StageEventSink,
) -> Dict[str, Any]:
    stage_options = dict(options or {})
    stage_options["preset"] = _text(preset) or "standard"
    stage_options["workflow_stage"] = stage
    spec = build_study_materials_agent_spec(
        query=topic,
        subject=subject,
        options=stage_options,
    )
    final_result: Dict[str, Any] | None = None
    async for event in run_codex_runtime_agent_events(
        task_type="study_materials",
        request={"stage": stage, "payload": payload},
        user_id=user_id,
        task_id=f"{task_id}-{stage}",
        spec=spec,
        final_event_type="result",
        prompt_override=build_stage_prompt(
            stage=stage,
            topic=topic,
            subject=subject,
            preset=preset,
            options=stage_options,
            payload=payload,
        ),
        result_schema=STAGE_RESULT_SCHEMA,
    ):
        event_type = _text(event.get("type") or event.get("event"))
        if event_type == "error":
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            raise StageResultError(_text(data.get("code")) or "codex_stage_failed", stage=stage, detail=_text(data.get("message")))
        if event_type == "done":
            raise StageResultError("invalid_stage_result", stage=stage, detail="task_level_done_not_allowed")
        if event_type == "result":
            final_result = event.get("result") if isinstance(event.get("result"), dict) else {}
            continue
        await event_sink(event)
    if final_result is None:
        raise StageResultError("invalid_stage_result", stage=stage, detail="stage_result_missing")
    return normalize_stage_result(stage, final_result)
