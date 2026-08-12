"""Unified trace events (design doc §9). Invariant: no hidden LLM/tool calls —
every call must happen at a layer that emits one of these events."""
from __future__ import annotations

from typing import Any, Dict

TRACE_EVENT_TYPES = frozenset({
    "thinking_delta",   # 统一思考增量（替代 legacy thinking / codex reasoning_delta）
    "note_write",       # 笔记落笔 {name, chars}
    "todo_update",      # TODO 状态变更 {todo: {...}}
    "tool_call",        # 工具调用（补 agent_path；沿用现有 data 形状）
    "research_budget",  # 研究阶段计划调用量 {mode, knowledge_points, ...}
    "figure_trace",     # 配图代码/渲染尝试/产物 {figure_id, stage, ...}
    "section_fill",     # 填充开始/完成 {sec_id, status}
    "text_delta",       # 成稿快照（沿用现有）
    "progress",         # 长任务阶段进度 {progress, stage}
})


def make_event(event_type: str, *, agent_path: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if event_type not in TRACE_EVENT_TYPES:
        raise ValueError(f"undeclared trace event type: {event_type}")
    return {"type": event_type, "agent_path": agent_path, "data": data}
