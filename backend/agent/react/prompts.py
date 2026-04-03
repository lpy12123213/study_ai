from __future__ import annotations

import json
from typing import Any, Dict, List

from backend.agent.types import CompressedContext


REACT_CONTROLLER_SYSTEM_PROMPT = """你是一个工具驱动的学习资料生成代理（ReAct）。你的目标是通过多轮工具调用完成任务。

你可以调用任意可用工具来检索、聚合、生成、审查并导出最终自学材料。

重要约束：
- 每一轮你都必须输出严格 JSON 对象，且只能输出 JSON（不要 Markdown、不要代码块、不要额外解释）。
- JSON 字段：
  - thought: string，简短说明你为什么要做这一步（允许 1-3 句）
  - action: string，下一步要做什么：要么是某个工具名，要么是 "finish"
  - arguments: object，给工具的参数（action 是工具时必填；finish 时可为空）
  - note: string，可选，对当前状态的简短备注（可空）

当 action="finish" 时，表示你认为已具备足够结果，系统将进入收尾导出与审查。
"""


def _wm_summary(ctx: CompressedContext) -> str:
    wm = ctx.working_memory if isinstance(ctx.working_memory, dict) else {}
    if not wm:
        return "（空）"

    parts: List[str] = []

    split_res = wm.get("split_knowledge_points")
    if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
        kps = [str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()]
        if kps:
            parts.append(f"- knowledge_points: {len(kps)} ({', '.join(kps[:6])}{'...' if len(kps) > 6 else ''})")

    material = wm.get("generate_study_material")
    if isinstance(material, dict) and isinstance(material.get("sections"), list):
        secs = [x for x in (material.get("sections") or []) if isinstance(x, dict)]
        parts.append(f"- sections: {len(secs)}")

    md = wm.get("markdown")
    if isinstance(md, str) and md.strip():
        parts.append(f"- markdown_chars: {len(md)}")

    for url_key in ("md_url", "tex_url", "pdf_url"):
        v = wm.get(url_key)
        if isinstance(v, str) and v.strip():
            parts.append(f"- {url_key}: yes")

    review = wm.get("review_content")
    if isinstance(review, dict):
        passed = review.get("passed")
        if isinstance(passed, bool):
            parts.append(f"- review_content.passed: {passed}")

    if wm.get("_abort_execution"):
        parts.append("- _abort_execution: true")

    if not parts:
        # Keep this small; do not dump keys blindly.
        keys = [str(k) for k in list(wm.keys())[:12]]
        parts.append(f"- keys: {', '.join(keys)}{'...' if len(wm.keys()) > 12 else ''}")

    return "\n".join(parts)


def _format_tools(tools: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        desc = str(t.get("description") or "").strip()
        if desc:
            lines.append(f"- {name}: {desc}")
        else:
            lines.append(f"- {name}")
        if len(lines) >= 80:
            lines.append("- ...")
            break
    return "\n".join(lines) if lines else "（无工具）"


def build_react_messages(
    *,
    ctx: CompressedContext,
    topic: str,
    subject: str,
    tools: List[Dict[str, Any]],
    scratchpad: str,
    iteration: int,
    max_iterations: int,
) -> List[Dict[str, str]]:
    preset = ""
    requirements = ""
    study_opts = ctx.working_memory.get("study_options") if isinstance(ctx.working_memory, dict) else {}
    if isinstance(study_opts, dict):
        preset = str(study_opts.get("preset") or "").strip()
        requirements = str(study_opts.get("requirements") or "").strip()

    user_prompt = (
        "任务：为用户生成可自学的学习资料（Markdown），并尽量完成导出与审查。\n\n"
        f"- topic: {topic}\n"
        f"- subject: {subject}\n"
        f"- preset: {preset or 'standard'}\n"
        f"- requirements: {requirements or '（无）'}\n"
        f"- iteration: {iteration + 1}/{max_iterations}\n\n"
        "当前工作记忆摘要（你可以据此决定下一步缺什么）：\n"
        f"{_wm_summary(ctx)}\n\n"
        "历史（Thought/Action/Observation 简述，可能为空）：\n"
        f"{scratchpad or '（空）'}\n\n"
        "可用工具列表（action 必须从中选择，或输出 finish）：\n"
        f"{_format_tools(tools)}\n\n"
        "现在请输出严格 JSON：\n"
        '{"thought":"...","action":"...","arguments":{...},"note":""}\n'
    )

    return [
        {"role": "system", "content": REACT_CONTROLLER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

