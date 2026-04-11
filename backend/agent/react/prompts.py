from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.agent.types import CompressedContext


REACT_CONTROLLER_SYSTEM_PROMPT = """你是一个工具驱动的学习资料生成代理（ReAct）。你的目标是通过多轮工具调用完成任务（检索→聚合→写作→审查→导出）。

你可以调用任意可用工具来检索、聚合、生成、审查并导出最终自学材料。

重要约束：
- 每一轮你都必须输出严格 JSON 对象，且只能输出 JSON（不要 Markdown、不要代码块、不要额外解释）。
- JSON 字段：
  - thought: string，简短说明你为什么要做这一步（允许 1-3 句）
  - action: string，下一步要做什么：要么是某个工具名，要么是 "finish"
  - batch_mode: string，可选。为空/不填表示单次调用；"per_knowledge_point" 表示对每个知识点并行执行同一个工具（提升效率）。
  - arguments: object，给工具的参数（action 是工具时必填；finish 时可为空）
  - note: string，可选，对当前状态的简短备注（可空）

当 action="finish" 时，表示你认为已具备足够结果，系统将进入收尾导出与审查。

质量门控（非常重要）：
- 你会在历史 scratchpad 中看到每步的 `Quality: HIGH|MEDIUM|LOW|FAILED (reason)`。
- 当 Quality=LOW 时，不要机械重复同一个 action；优先更换策略：
  - 改 query_hint（从定义/性质/边界/反例/证明/应用等维度拆分）
  - 换工具（例如 wikipedia_search / mediawiki_search / stackexchange_search / github_search）
  - 或者暂时跳过该知识点，先推进其它 KP，避免在单点上“无限重试”

典型 8 阶段流程（可重排/可跳过，但避免来回打转）：
1) split_knowledge_points / review_knowledge_points：得到合理的知识点列表
2) web_search_knowledge：为每个 KP 找到足量高质量来源（必要时多轮 + query_hint）
3) wikipedia_search / mediawiki_search：补充权威定义/术语
4) browse_web_pages：对高质量链接抓取正文（当 snippet 质量低时）
5) aggregate_knowledge / synthesize_sources：聚合并去噪为可写作的结构化输入
6) generate_study_material：按 KP 生成讲解（覆盖全部 KP）
7) assemble_study_archive / save_markdown_file / export_*：组装与导出
8) review_content：审查；不通过则回到检索/修订阶段

预算意识：
- 你的工具迭代次数和 LLM 决策次数都有限。优先“覆盖所有知识点并通过 review”，而不是把单个 KP 打磨到完美。
- 当 budget_remaining 很低时，优先收尾：assemble/save/export/review，然后 finish。

batch_mode 用法（推荐）：
- 当你要对“所有知识点”执行同一个工具时，设置 batch_mode="per_knowledge_point"。
- 推荐 batch_mode 的工具：
  - web_search_knowledge、wikipedia_search、mediawiki_search
  - github_search、stackexchange_search、search_questions_by_knowledge
  - synthesize_sources、generate_study_material
- 不推荐 batch_mode 的工具：需要手动 URLs 的 browse_web_pages 等（更适合针对少数 KP 精准使用）。
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
    budget_remaining: int,
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
        f"- tool_iterations_remaining: {max(0, max_iterations - (iteration + 1))}\n"
        f"- budget_remaining: {max(0, int(budget_remaining or 0))}\n\n"
        "当前工作记忆摘要（你可以据此决定下一步缺什么）：\n"
        f"{_wm_summary(ctx, budget_remaining=budget_remaining)}\n\n"
        "历史（Thought/Action/Quality/Observation 简述，可能为空）：\n"
        f"{scratchpad or '（空）'}\n\n"
        "可用工具列表（action 必须从中选择，或输出 finish）：\n"
        f"{_format_tools(tools)}\n\n"
        "现在请输出严格 JSON：\n"
        '{"thought":"...","action":"...","batch_mode":"","arguments":{...},"note":""}\n'
    )

    return [
        {"role": "system", "content": REACT_CONTROLLER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
