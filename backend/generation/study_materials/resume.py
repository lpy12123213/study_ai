
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.core.text_utils import clip_text as _clip_text

logger = get_logger(__name__)


def _truthy(value: Any) -> bool:
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _infer_stage_from_tool(tool_name: str) -> str:
    """Map a tool name to a coarse stage label used for resumable/continue UX."""

    t = str(tool_name or "").strip()
    if not t:
        return ""

    if t in {
        "web_search_knowledge",
        "browse_web_pages",
        "wikipedia_search",
        "mediawiki_search",
        "github_search",
        "stackexchange_search",
        "search_questions_by_knowledge",
    }:
        return "search"

    if t in {"aggregate_knowledge", "synthesize_sources", "detect_knowledge_type"}:
        return "aggregate"

    if t in {
        "generate_outline",
        "generate_study_material",
        "critique_draft",
        "refine_draft",
        "generate_diagrams",
        "assemble_study_archive",
        "review_content",
        "revise_markdown",
    }:
        return "write"

    if t in {"export_study_markdown", "convert_markdown_to_latex", "refine_latex", "compile_latex_to_pdf"}:
        return "export"

    return ""


def _derive_resume_state(wm: Dict[str, Any]) -> Dict[str, Any]:
    """Derive best-effort resume metadata from a working_memory snapshot."""

    step_results = wm.get("step_results") if isinstance(wm, dict) else None
    step_results = step_results if isinstance(step_results, list) else []

    last_success_step: Dict[str, Any] = {}
    last_failed_step: Dict[str, Any] = {}
    last_success_stage = ""
    last_failed_stage = ""
    unknown_tools: set[str] = set()

    for it in step_results:
        if not isinstance(it, dict):
            continue
        tool = str(it.get("tool") or "").strip()
        if not tool:
            continue
        success = bool(it.get("success"))
        stage = _infer_stage_from_tool(tool)
        if not stage:
            # B17: 未知工具推断不出阶段时记录告警，避免静默沿用陈旧 stage 造成错误的续作目标。
            unknown_tools.add(tool)
        record = {
            "step_id": str(it.get("step_id") or "").strip(),
            "tool": tool,
            "success": success,
            "error": str(it.get("error") or "").strip() or None,
        }
        if success:
            last_success_step = record
            last_success_stage = stage or last_success_stage
        else:
            last_failed_step = record
            last_failed_stage = stage or last_failed_stage

    if unknown_tools:
        logger.warning(
            "study_materials_resume_stage_inference_empty",
            extra={"tools": sorted(unknown_tools)},
        )

    out: Dict[str, Any] = {}
    if last_success_step:
        out["last_success_step"] = last_success_step
    if last_failed_step:
        out["last_failed_step"] = last_failed_step
    if last_success_stage:
        out["last_success_stage"] = last_success_stage
    if last_failed_stage:
        out["last_failed_stage"] = last_failed_stage
    # B9: 透出 previous_attempt（retry_search/replan 前封存的上次产物），供 API 展示。
    previous_attempt = wm.get("previous_attempt") if isinstance(wm, dict) else None
    if isinstance(previous_attempt, dict) and previous_attempt:
        out["previous_attempt"] = previous_attempt
    return out


def _prune_resume_working_memory(
    wm: Dict[str, Any],
    *,
    mode: str,
    last_failed_stage: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a pruned working_memory snapshot for stage-based continuation modes."""

    mode_norm = str(mode or "").strip().lower()
    stage = str(last_failed_stage or "").strip().lower()
    if mode_norm == "retry_search":
        # B9: 仅在失败确实发生在检索链路（search/read/aggregate）时才强制回到 search；
        # write/export 阶段的失败应回到该阶段本身，只丢弃其下游键，避免误毁成稿。
        if stage not in {"write", "export"}:
            stage = "search"
    elif mode_norm == "resume_failed_stage" and not stage:
        stage = "write"

    keep_keys = {"split_knowledge_points", "review_knowledge_points", "study_options"}

    # B9: 丢弃前先把本轮产物封存到 previous_attempt，调用方/前端仍可回看上一版内容。
    salvage_keys = ("markdown", "study_material", "outlines", "aggregated", "review_content", "diagrams")
    stash: Dict[str, Any] = {}
    for key in salvage_keys:
        value = (wm or {}).get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        stash[key] = value
    previous_attempt: Dict[str, Any] = {}
    if stash:
        previous_attempt = {"dropped_at_stage": stage, "keys": stash}

    drop_keys: set[str] = set()
    if stage == "search":
        drop_keys |= {
            "web_search_knowledge",
            "browse_web_pages",
            "wikipedia_search",
            "mediawiki_search",
            "github_search",
            "stackexchange_search",
            "search_questions_by_knowledge",
            "aggregate_knowledge",
            "aggregated",
            "aggregate",
            "source_briefs",
            "source_facts",
            "knowledge_types",
            "outlines",
            "generate_outline",
            "generate_study_material",
            "study_material",
            "critique_draft",
            "refine_draft",
            "diagrams",
            "assemble_study_archive",
            "review_content",
            "revise_markdown",
            "markdown",
            "md_url",
            "md_filename",
            "tex_url",
            "tex_filename",
            "pdf_url",
            "pdf_filename",
            "latex_tex",
            "_latex_compile_round",
            "_latex_last_compile_error",
        }
    elif stage == "aggregate":
        drop_keys |= {
            "aggregate_knowledge",
            "aggregated",
            "aggregate",
            "source_briefs",
            "source_facts",
            "knowledge_types",
            "outlines",
            "generate_outline",
            "generate_study_material",
            "study_material",
            "critique_draft",
            "refine_draft",
            "diagrams",
            "assemble_study_archive",
            "review_content",
            "revise_markdown",
            "markdown",
            "md_url",
            "md_filename",
            "tex_url",
            "tex_filename",
            "pdf_url",
            "pdf_filename",
            "latex_tex",
            "_latex_compile_round",
            "_latex_last_compile_error",
        }
    elif stage == "write":
        drop_keys |= {
            "generate_outline",
            "generate_study_material",
            "study_material",
            "critique_draft",
            "refine_draft",
            "diagrams",
            "assemble_study_archive",
            "review_content",
            "revise_markdown",
            "markdown",
            "md_url",
            "md_filename",
            "tex_url",
            "tex_filename",
            "pdf_url",
            "pdf_filename",
            "latex_tex",
            "_latex_compile_round",
            "_latex_last_compile_error",
        }
    elif stage == "export":
        drop_keys |= {
            "md_url",
            "md_filename",
            "tex_url",
            "tex_filename",
            "pdf_url",
            "pdf_filename",
            "latex_tex",
            "_latex_compile_round",
            "_latex_last_compile_error",
        }

    out: Dict[str, Any] = {}
    for k, v in (wm or {}).items():
        key = str(k or "").strip()
        if not key:
            continue
        if key in keep_keys:
            out[key] = v
            continue
        if key in drop_keys:
            continue
        out[key] = v
    if previous_attempt:
        out["previous_attempt"] = previous_attempt
    return out


def _workflow_review_target(workflow: Dict[str, Any]) -> str:
    """B16: review 续作前置检查——无成稿时回 draft（无计划时回 plan）。"""

    if str(workflow.get("markdown") or "").strip():
        return "review"
    plan = workflow.get("plan") if isinstance(workflow.get("plan"), dict) else {}
    return "draft" if plan else "plan"


def _set_workflow_resume_stage(
    wm: Dict[str, Any],
    *,
    mode: str,
    last_failed_stage: Optional[str] = None,
) -> Dict[str, Any]:
    out = dict(wm or {})
    workflow_raw = out.get("study_materials_workflow")
    if not isinstance(workflow_raw, dict):
        return out
    workflow = dict(workflow_raw)
    mode_norm = str(mode or "").strip().lower()
    if mode_norm == "improve":
        workflow["stage"] = _workflow_review_target(workflow)
    elif mode_norm in {"deepen_research", "retry_search"}:
        workflow["stage"] = "research"
        if mode_norm == "deepen_research":
            # B8: 新的改进周期从零开始计修订次数，避免旧 revision_attempts 直接耗尽预算。
            workflow["revision_attempts"] = 0
        if str(workflow.get("markdown") or out.get("markdown") or "").strip():
            workflow["resume_after_research"] = "review"
    elif mode_norm == "replan_from_failure":
        workflow["stage"] = "plan"
    elif mode_norm == "resume_failed_stage":
        failure = workflow.get("last_failure") if isinstance(workflow.get("last_failure"), dict) else {}
        failed = str(failure.get("stage") or "").strip()
        current = str(workflow.get("stage") or "").strip().lower()
        if not failed and current in {"plan", "research", "draft", "review", "revise", "accept"}:
            failed = current
        if not failed:
            legacy_stage = str(last_failed_stage or "").strip().lower()
            failed = {"search": "research", "aggregate": "research", "write": "review", "export": "review"}.get(
                legacy_stage,
                "review",
            )
        if failed == "review":
            # B16: 与 improve 相同的成稿前置检查，空稿不应直接进 review。
            failed = _workflow_review_target(workflow)
        workflow["stage"] = failed
    out["study_materials_workflow"] = workflow
    return out


def _refresh_resume_meta(*, meta: Dict[str, Any]) -> None:
    """Refresh resumable metadata based on the latest working_memory snapshot (best-effort)."""

    wm = meta.get("resume_working_memory") if isinstance(meta, dict) else None
    wm = wm if isinstance(wm, dict) else {}

    state = _derive_resume_state(wm)
    if isinstance(state.get("last_success_step"), dict):
        meta["last_success_step"] = dict(state.get("last_success_step") or {})
    if isinstance(state.get("last_failed_step"), dict):
        meta["last_failed_step"] = dict(state.get("last_failed_step") or {})
    meta["last_success_stage"] = str(state.get("last_success_stage") or "").strip()
    meta["last_failed_stage"] = str(state.get("last_failed_stage") or "").strip()

    def _extract_kps() -> List[str]:
        split_res = wm.get("split_knowledge_points")
        if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
            kps = [str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()]
            if kps:
                return kps[:15]
        return []

    def _map_by_kp(blob: Any) -> Dict[str, Dict[str, Any]]:
        if not isinstance(blob, dict):
            return {}
        if isinstance(blob.get("items"), list):
            out: Dict[str, Dict[str, Any]] = {}
            for it in blob.get("items") or []:
                if not isinstance(it, dict):
                    continue
                kp = str(it.get("knowledge_point") or "").strip()
                if kp:
                    out[kp] = dict(it)
            return out
        kp = str(blob.get("knowledge_point") or "").strip()
        return {kp: dict(blob)} if kp else {}

    web_map = _map_by_kp(wm.get("web_search_knowledge"))
    search_summary_by_kp: Dict[str, Any] = {}
    for kp, it in web_map.items():
        provider = str(it.get("provider") or "").strip()
        query = str(it.get("query") or it.get("base_query") or "").strip()
        results = it.get("results") if isinstance(it.get("results"), list) else []
        summarized: List[Dict[str, Any]] = []
        for r in [x for x in results if isinstance(x, dict)][:8]:
            url = str(r.get("url") or "").strip()
            if not url:
                continue
            summarized.append(
                {
                    "title": str(r.get("title") or "").strip(),
                    "url": url,
                    "snippet": _clip_text(str(r.get("snippet") or ""), max_chars=240),
                    "source_query": str(r.get("source_query") or r.get("sourceQuery") or "").strip(),
                }
            )
        search_summary_by_kp[kp] = {"provider": provider, "query": query, "results": summarized}
    meta["search_summary_by_kp"] = search_summary_by_kp

    kps = _extract_kps() or list(search_summary_by_kp.keys())[:15]
    aggregated_map = _map_by_kp(wm.get("aggregated") or wm.get("aggregate_knowledge"))
    wiki_map = _map_by_kp(wm.get("wikipedia_search"))
    mw_map = _map_by_kp(wm.get("mediawiki_search"))

    material_blob = wm.get("generate_study_material") if isinstance(wm.get("generate_study_material"), dict) else None
    if material_blob is None:
        material_blob = wm.get("study_material") if isinstance(wm.get("study_material"), dict) else {}
    sections_blob = material_blob.get("sections") if isinstance(material_blob, dict) else None
    sections_list = [s for s in (sections_blob or []) if isinstance(s, dict)] if isinstance(sections_blob, list) else []
    sec_by_kp: Dict[str, Dict[str, Any]] = {}
    for sec in sections_list:
        kp = str(sec.get("knowledge_point") or "").strip()
        if kp and kp not in sec_by_kp:
            sec_by_kp[kp] = sec

    per_kp_state: Dict[str, Any] = {}
    for kp in kps:
        web = web_map.get(kp) or {}
        web_results = web.get("results") if isinstance(web.get("results"), list) else []
        web_n = len([x for x in web_results if isinstance(x, dict)])

        wiki = wiki_map.get(kp) or {}
        mw = mw_map.get(kp) or {}
        wiki_has = bool(str(wiki.get("summary") or wiki.get("content") or "").strip())
        mw_has = bool(str(mw.get("summary") or mw.get("content") or "").strip())

        search_ok = web_n > 0 or wiki_has or mw_has
        aggregate_ok = bool(aggregated_map.get(kp))
        sec = sec_by_kp.get(kp) or {}
        write_ok = bool(str(sec.get("explanation_markdown") or "").strip())

        per_kp_state[kp] = {
            "knowledge_point": kp,
            "search": search_ok,
            "aggregate": aggregate_ok,
            "write": write_ok,
            "web_results": web_n,
        }
    meta["per_kp_state"] = per_kp_state
