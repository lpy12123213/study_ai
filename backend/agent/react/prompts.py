from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.agent.planning.skill_catalog import SKILLS, normalize_active_skills, skills_for_domain
from backend.agent.planning.study_options import _study_flags
from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger
from backend.llm.client import cacheable_message
from backend.llm.prompts import create_llm_prompt_registry

logger = get_logger(__name__)


REACT_CONTROLLER_SYSTEM_PROMPT = """You are a tool-driven study-material generation agent (ReAct). Your goal is to produce high-quality self-study materials through tool calls: retrieval -> aggregation -> writing -> review -> export.

You may call available tools to retrieve, aggregate, generate, review, and export the final self-study material.
Match the language of the user's latest request for all user-facing prose unless the user explicitly asks for another language. Keep tool names, JSON field names, IDs, and enum values unchanged.

Choosing when to split knowledge points (重要)：
- 你需要自行决定是否拆分知识点。判断准则：
  * 主题宽泛/复合（涉及多个独立子概念）→ 拆分
  * 主题极聚焦（单一定理/单一公式/单一概念的简单解释）→ 不拆分，直接进入检索
  * 已有 working memory 中含 split_knowledge_points 结果 → 不要重复拆分
- **拆分方式（首选直接拆分，省一轮工具调用）**：
  * 优先使用特殊 action `set_knowledge_points`：你直接给出 knowledge_points 数组，系统会立即写入 working memory，**不会消耗 tool 预算**。示例：
    `{"action": "set_knowledge_points", "arguments": {"knowledge_points": ["KP1", "KP2", "KP3"]}}`
  * 仅在你对自己的拆分没把握、希望让一个独立的 LLM 做拆分+审核时，才调用 `split_knowledge_points` 工具。
- 拆分准则：3-8 个互不重复、互相独立、可单独检索的子知识点；每个 KP 用 2-12 字简洁概括。

Research depth policy（研究深度策略）：
- preset=quick：覆盖关键定义即可，2-3 类工具足够。
- preset=standard：每个 KP 至少做一次 web_search_knowledge + 一次 wikipedia/mediawiki，必要时 browse_web_pages。
- preset=deep：每个 KP 至少 2 类来源，遇到 Quality<HIGH 主动换工具/换 query_hint 重试。
- preset=research：每个 KP 强制覆盖至少 3 类来源（web_search + wikipedia/mediawiki + stackexchange/github_search 或 browse_web_pages），并在 Quality<HIGH 时再追加一轮检索；不要在仅做一次百科搜索后就结束。

重要约束：
- If the model client provides a `react_decision` tool/function, call that tool with the next decision.
- If tool/function calling is unavailable, output a strict JSON object only. Do not output Markdown, code fences, or extra explanation.
- JSON fields:
  - thought: string，简短说明你为什么要做这一步（允许 1-3 句）
  - action: string. The next action: either a tool name or "finish".
  - batch_mode: string, optional. Empty/missing means a single call; "per_knowledge_point" runs the same tool for each knowledge point in parallel.
  - arguments: object. Tool arguments; required when action is a tool and may be empty for finish.
  - note: string，可选，对当前状态的简短备注（可空）

When to finish：
- 仅当以下条件全部满足时才输出 action="finish"：
  1) 已生成 generate_study_material 且覆盖每个 KP（或主题已无需拆分）
  2) 已 assemble_study_archive 得到完整 Markdown
  3) 已 review_content 通过（passed=true）；若失败但已无预算补救，可以 finish
  4) 研究深度满足上面 preset 对应的最低要求
- 不要因为做了一两次检索、得到 Quality=MEDIUM 就提前 finish；研究模式下尤其要避免这一点。

质量门控（非常重要）：
- 你会在历史 scratchpad 中看到每步的 `Quality: HIGH|MEDIUM|LOW|FAILED (reason)`。
- When Quality=LOW, do not mechanically repeat the same action. Prefer changing strategy:
  - 改 query_hint（从定义/性质/边界/反例/证明/应用等维度拆分）
  - Switch tools, for example wikipedia_search, mediawiki_search, stackexchange_search, or github_search.
  - 或者暂时跳过该知识点，先推进其它 KP，避免在单点上"无限重试"

典型 8 阶段流程（可重排/可跳过，但避免来回打转）：
1) split_knowledge_points / review_knowledge_points：仅当主题需要分解时调用
2) web_search_knowledge：为每个 KP 找到足量高质量来源（必要时多轮 + query_hint）
3) wikipedia_search / mediawiki_search：补充权威定义/术语
4) browse_web_pages：对高质量链接抓取正文（当 snippet 质量低时）
5) aggregate_knowledge / synthesize_sources：聚合并去噪为可写作的结构化输入
6) generate_study_material: generate explanations by KP and cover every KP.
7) assemble_study_archive / save_markdown_file / export_*：组装与导出
8) review_content: review; if it fails, return to retrieval or revision.

预算意识：
- Tool iterations and LLM decisions are limited. 优先覆盖所有知识点 + 通过 review > 在单点上反复打磨。
- 当 budget_remaining 很低时，优先收尾：assemble/save/export/review，然后 finish。
- 但研究模式（preset=research）下：剩余预算允许时不要急于 finish，宁可多做一轮检索/补研究。

batch_mode 用法（推荐）：
- When running the same tool for all knowledge points, set batch_mode="per_knowledge_point".
- Recommended tools for batch_mode:
  - web_search_knowledge、wikipedia_search、mediawiki_search
  - github_search、stackexchange_search、search_questions_by_knowledge
  - synthesize_sources、generate_study_material
- Not recommended for batch_mode: tools requiring manual URLs, such as browse_web_pages. Use them precisely for a few KPs.
"""


def _wm_summary(ctx: CompressedContext, *, budget_remaining: Optional[int] = None) -> str:
    wm = ctx.working_memory if isinstance(ctx.working_memory, dict) else {}
    if not wm:
        return "（空）"

    parts: List[str] = []

    def _map_by_point(blob: Any) -> Dict[str, Dict[str, Any]]:
        if not isinstance(blob, dict):
            return {}
        items = blob.get("items")
        if isinstance(items, list):
            mapped: Dict[str, Dict[str, Any]] = {}
            for it in items:
                if not isinstance(it, dict):
                    continue
                kp = str(it.get("knowledge_point") or "").strip()
                if not kp:
                    continue
                mapped[kp] = it
            return mapped
        kp = str(blob.get("knowledge_point") or "").strip()
        return {kp: blob} if kp else {}

    kps: List[str] = []
    split_res = wm.get("split_knowledge_points")
    if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
        kps = [str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()]
        if kps:
            parts.append(f"- knowledge_points: {len(kps)} ({', '.join(kps[:6])}{'...' if len(kps) > 6 else ''})")

    # Progress: research coverage per KP (best-effort heuristic).
    if kps:
        researched: set[str] = set()

        web_map = _map_by_point(wm.get("web_search_knowledge"))
        browse_map = _map_by_point(wm.get("browse_web_pages"))
        wiki_map = _map_by_point(wm.get("wikipedia_search"))
        mw_map = _map_by_point(wm.get("mediawiki_search"))
        gh_map = _map_by_point(wm.get("github_search"))
        se_map = _map_by_point(wm.get("stackexchange_search"))
        q_map = _map_by_point(wm.get("search_questions_by_knowledge"))

        briefs = wm.get("source_briefs")
        briefs = dict(briefs) if isinstance(briefs, dict) else {}

        def _has_list(it: Dict[str, Any], key: str) -> bool:
            v = it.get(key)
            return isinstance(v, list) and len([x for x in v if x]) > 0

        for kp in kps:
            it = web_map.get(kp) or {}
            if _has_list(it, "results") or str(it.get("summary") or "").strip():
                researched.add(kp)
                continue

            it = browse_map.get(kp) or {}
            if _has_list(it, "pages"):
                researched.add(kp)
                continue

            it = wiki_map.get(kp) or {}
            if str(it.get("summary") or it.get("content") or "").strip():
                researched.add(kp)
                continue

            it = mw_map.get(kp) or {}
            if str(it.get("summary") or it.get("content") or "").strip():
                researched.add(kp)
                continue

            it = gh_map.get(kp) or {}
            if _has_list(it, "results"):
                researched.add(kp)
                continue

            it = se_map.get(kp) or {}
            if _has_list(it, "results"):
                researched.add(kp)
                continue

            it = q_map.get(kp) or {}
            if any(_has_list(it, k) for k in ("questions", "examples", "exercises")):
                researched.add(kp)
                continue

            if kp in briefs and briefs.get(kp):
                researched.add(kp)

        parts.append(f"- research_progress: {len(researched)}/{len(kps)} KP")

    material = wm.get("generate_study_material")
    if isinstance(material, dict) and isinstance(material.get("sections"), list):
        secs = [x for x in (material.get("sections") or []) if isinstance(x, dict)]
        parts.append(f"- sections: {len(secs)}")

        if kps:
            done_kps = {
                str(x.get("knowledge_point") or "").strip()
                for x in secs
                if str(x.get("knowledge_point") or "").strip()
            }
            parts.append(f"- material_progress: {len(done_kps)}/{len(kps)} KP")

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

    last_ref = wm.get("last_reflection")
    if isinstance(last_ref, dict):
        passed = last_ref.get("passed")
        if isinstance(passed, bool):
            parts.append(f"- last_reflection.passed: {passed}")
        issues = last_ref.get("issues") if isinstance(last_ref.get("issues"), list) else []
        issues = [str(x or "").strip() for x in issues if str(x or "").strip()]
        if issues:
            preview = "；".join(issues[:3])
            parts.append(f"- last_reflection.issues: {len(issues)} ({preview}{'…' if len(issues) > 3 else ''})")

    if budget_remaining is not None:
        parts.append(f"- budget_remaining: {int(budget_remaining)}")

    if wm.get("_abort_execution"):
        parts.append("- _abort_execution: true")

    if not parts:
        # Keep this small; do not dump keys blindly.
        keys = [str(k) for k in list(wm.keys())[:12]]
        parts.append(f"- keys: {', '.join(keys)}{'...' if len(wm.keys()) > 12 else ''}")

    return "\n".join(parts)


def _skill_manifest(*, domain: str = "study", enable_diagrams: bool = True) -> str:
    """Render the static available-skill manifest (name + one-liner).

    Lists EVERY skill loadable in this run's domain + flags, not just the
    loaded ones, so the stable (cacheable) message stays byte-identical across
    load_skill calls within a run. The loaded/unloaded state and the full skill
    instructions live in the per-iteration decision message instead.
    """
    lines = ["Available skills (tool groups). 调用 load_skill 可按需展开其工具集（不消耗额外 LLM 预算）："]
    shown = 0
    for name in skills_for_domain(domain, enable_diagrams=enable_diagrams):
        skill = SKILLS.get(name)
        if not skill:
            continue
        lines.append(f"- {name}: {skill['one_liner']}")
        shown += 1
        if shown >= 12:
            break
    lines.append("建议导航：planning → research → writing → export；examples/diagrams 按需 load_skill。")
    return "\n".join(lines)


def _loaded_skill_instructions(ctx: CompressedContext) -> str:
    """Render the FULL instructions of the currently loaded skills.

    Injected into the per-iteration decision message (reassembled every round,
    never scratchpad-clipped, and outside the cacheable stable prefix), so the
    controller LLM always sees the complete `agent.skills.<name>.v1` guidance
    for every skill in active_skills.
    """
    wm = ctx.working_memory if isinstance(ctx.working_memory, dict) else {}
    active = normalize_active_skills(wm.get("active_skills"))

    registry = create_llm_prompt_registry()
    parts: List[str] = []
    for name in active:
        skill = SKILLS.get(name)
        if not skill:
            continue
        try:
            content = registry.render(skill["prompt_id"]).content
        except Exception:
            logger.exception("react_skill_instruction_render_failed", extra={"skill": name})
            content = skill["one_liner"]
        parts.append(f"### {name}\n{str(content or '').strip()}")

    if not parts:
        return ""
    return "Loaded skill instructions（已加载 skill 的完整指引）：\n" + "\n\n".join(parts)


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
    return "\n".join(lines) if lines else "(no tools)"


def _controller_system_prompt() -> str:
    try:
        return create_llm_prompt_registry().render("agent.react.controller.v1").content
    except Exception:
        logger.exception("react_prompt_registry_fallback_failed")
        return REACT_CONTROLLER_SYSTEM_PROMPT


def build_react_messages(
    *,
    ctx: CompressedContext,
    topic: str,
    subject: str,
    tools: List[Dict[str, Any]],
    scratchpad: str,
    iteration: int,
    max_iterations: int,
    budget_remaining: int,
    skills_mode: bool = False,
) -> List[Dict[str, Any]]:
    preset = ""
    requirements = ""
    study_opts = ctx.working_memory.get("study_options") if isinstance(ctx.working_memory, dict) else {}
    if isinstance(study_opts, dict):
        preset = str(study_opts.get("preset") or "").strip()
        requirements = str(study_opts.get("requirements") or "").strip()

    stable_context_prompt = (
        "Task: generate self-study material for the user in Markdown, and complete export and review when possible.\n\n"
        f"- topic: {topic}\n"
        f"- subject: {subject}\n"
        f"- preset: {preset or 'standard'}\n"
        f"- requirements: {requirements or '（无）'}\n"
        "Current working-memory summary. Use it to decide what is missing next:\n"
        f"{_wm_summary(ctx)}\n"
    )

    if skills_mode:
        # Static manifest: identical for the whole run, so the cacheable stable
        # message no longer flips when load_skill changes active_skills.
        flags = _study_flags(ctx)
        stable_context_prompt += "\n" + _skill_manifest(enable_diagrams=bool(flags.get("enable_diagrams", True))) + "\n"

    special_actions = [
        "",
        "Special inline actions (no tool call, no LLM round-trip):",
        "- set_knowledge_points: directly write knowledge_points to memory.",
        '  arguments: {"knowledge_points": ["KP1", "KP2", ...]} (3-8 items recommended).',
        "  Use this instead of the split_knowledge_points tool when you can confidently split the topic yourself.",
    ]
    if skills_mode:
        # load_skill only exists in skills mode; keep its docs out of legacy runs.
        special_actions += [
            "- load_skill: 按需加载一个 skill，立即展开其工具集（本动作不消耗额外 LLM 预算）。",
            '  arguments: {"skill": "research"}。全部可用 skill 见上方 Available skills 清单；'
            "已加载 skill 的完整指令见下方 Loaded skill instructions。",
        ]

    decision_parts = [
        f"- iteration: {iteration + 1}/{max_iterations}",
        "",
        f"- tool_iterations_remaining: {max(0, max_iterations - (iteration + 1))}",
        f"- budget_remaining: {max(0, int(budget_remaining or 0))}",
        "",
        "历史（Thought/Action/Quality/Observation 简述，可能为空）：",
        scratchpad or "（空）",
        "",
        "Available tools. action must be one of these tools, finish, or one of the special actions below:",
        _format_tools(tools),
        *special_actions,
    ]
    if skills_mode:
        # Full instructions for loaded skills: reassembled each iteration (no
        # scratchpad truncation) and kept out of the cacheable stable prefix.
        loaded_block = _loaded_skill_instructions(ctx)
        if loaded_block:
            decision_parts += ["", loaded_block]
    decision_parts += [
        "",
        "Now output strict JSON:",
        '{"thought":"...","action":"...","batch_mode":"","arguments":{...},"note":""}',
    ]
    decision_prompt = "\n".join(decision_parts)

    return [
        cacheable_message("system", _controller_system_prompt()),
        cacheable_message("user", stable_context_prompt),
        {"role": "user", "content": decision_prompt},
    ]
