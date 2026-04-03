from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.core.settings import LESSON_PLAN_MODEL
from backend.llm.client import is_llm_configured
from backend.question_library.diagram_utils import render_schematic_to_url, render_svg_to_url, render_tikz_to_url
from backend.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.question_library.subject_knowledge import infer_subject_family

logger = get_logger(__name__)


def _heuristic_need_diagram(*, subject: str, stem: str) -> bool:
    fam = infer_subject_family(subject)
    s = str(stem or "")
    # Physics tends to benefit from a figure (even a minimal schematic).
    if fam == "physics":
        return True
    if fam == "math":
        for kw in ["如图", "图中", "几何", "三角形", "圆", "直线", "平面", "空间", "坐标系", "椭圆", "抛物线"]:
            if kw in s:
                return True
        return False
    return any(kw in s for kw in ["如图", "示意图", "图1", "图 1"])


async def assess_diagram_need(
    draft: dict,
    *,
    subject: str,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    """LLM-assisted decision: should we attach a diagram? (best-effort)."""

    stem = str((draft or {}).get("stem") or "").strip()
    if not stem:
        return {"need_diagram": False, "kind": "none", "reason": "empty_stem"}

    # If LLM isn't available, rely on a conservative heuristic.
    if not is_llm_configured():
        return {"need_diagram": _heuristic_need_diagram(subject=subject, stem=stem), "kind": "auto", "reason": "heuristic"}

    fam = infer_subject_family(subject)
    payload: Dict[str, Any] = {
        "subject": str(subject or "").strip(),
        "subject_family": fam,
        "stem": _clip(stem, 1200),
        "output_schema": {
            "need_diagram": "bool",
            "kind": "string (svg|schematic|tikz|none)",
            "reason": "string",
        },
    }

    system_content = (
        "<role>你是审题教研员，负责判断题目是否需要配图。</role>\n"
        "<rules>\n"
        "  <rule>只有当缺少配图会明显增加歧义或阅读难度，才 need_diagram=true。</rule>\n"
        "  <rule>优先选择可用的轻量方案：几何/函数示意图用 svg；物理过程/受力/电路用 schematic。</rule>\n"
        "  <rule>除非必须使用 TikZ 才能表达，否则不要选择 tikz。</rule>\n"
        "</rules>\n"
        "<output_format>严格输出 JSON object。</output_format>"
    )

    text = await _chat_json_with_reasoning(
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.15,
        max_tokens=0,
        req_id_prefix="ql_diagram_need",
        retries=2,
        raise_on_fail=False,
        stage_id="diagram_generation",
        stage_label="配图生成",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    kind = str(obj.get("kind") or "").strip().lower()
    if kind not in {"svg", "schematic", "tikz", "none"}:
        kind = "auto"
    return {
        "need_diagram": bool(obj.get("need_diagram")),
        "kind": kind,
        "reason": str(obj.get("reason") or "").strip(),
    }


async def generate_question_diagram(
    draft: dict,
    *,
    subject: str,
    user_id: str,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> Optional[dict]:
    """Generate a single diagram for a draft question and publish it."""

    stem = str((draft or {}).get("stem") or "").strip()
    if not stem:
        return None

    fam = infer_subject_family(subject)
    prefer = "schematic" if fam == "physics" else "svg"

    if not is_llm_configured():
        # Without LLM, we can't reliably build a spec; return None.
        return None

    payload: Dict[str, Any] = {
        "subject": str(subject or "").strip(),
        "subject_family": fam,
        "preferred_kind": prefer,
        "stem": _clip(stem, 1400),
        "output_schema": {
            "need_diagram": "bool",
            "kind": "string (svg|schematic|tikz|none)",
            "alt": "string",
            "caption": "string",
            "svg_spec": "object (when kind=svg, backend.core.svg_diagram.render_svg_diagram spec)",
            "schematic_spec": "object (when kind=schematic, backend.core.plot_tools.render_schematic spec)",
            "tikz": "string (when kind=tikz)",
        },
    }

    system_content = (
        "<role>你是配图助教，负责为题目生成最小必要示意图。</role>\n"
        "<constraints>\n"
        "  <rule>图必须服务于题意：标注关键点/方向/量，不要画装饰性内容。</rule>\n"
        "  <rule>若题目不需要图，need_diagram=false 并 kind=none。</rule>\n"
        "  <rule>优先输出 preferred_kind 对应的 spec；TikZ 仅在必须时使用。</rule>\n"
        "  <rule>所有坐标/标注必须在 spec 中明确，不要依赖隐含约定。</rule>\n"
        "</constraints>\n"
        "<output_format>严格输出 JSON object。</output_format>"
    )

    text = await _chat_json_with_reasoning(
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.25,
        max_tokens=0,
        req_id_prefix="ql_diagram_spec",
        retries=2,
        raise_on_fail=False,
        stage_id="diagram_generation",
        stage_label="配图生成",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    if not bool(obj.get("need_diagram")):
        return None

    kind = str(obj.get("kind") or prefer).strip().lower()
    if kind not in {"svg", "schematic", "tikz"}:
        kind = prefer

    alt = str(obj.get("alt") or "diagram").strip() or "diagram"
    caption = str(obj.get("caption") or "").strip()

    try:
        if kind == "schematic":
            spec = obj.get("schematic_spec") if isinstance(obj.get("schematic_spec"), dict) else {}
            published = await render_schematic_to_url(spec=spec, user_id=user_id, alt=alt)
        elif kind == "tikz":
            tikz = str(obj.get("tikz") or "").strip()
            published = await render_tikz_to_url(tikz=tikz, user_id=user_id, alt=alt)
        else:
            spec = obj.get("svg_spec") if isinstance(obj.get("svg_spec"), dict) else {}
            published = await render_svg_to_url(spec=spec, user_id=user_id, alt=alt)
    except Exception as exc:
        logger.debug("question_library_diagram_render_failed", exc_info=True, extra={"subject": subject})
        return {"kind": kind, "success": False, "error": str(exc)}

    if not isinstance(published, dict) or not published.get("success"):
        return {"kind": kind, "success": False, "error": str((published or {}).get("error") or "render_failed")}

    return {
        "kind": kind,
        "url": str(published.get("url") or "").strip(),
        "filename": str(published.get("filename") or "").strip(),
        "media_id": str(published.get("media_id") or published.get("sha256") or "").strip(),
        "alt": alt,
        "caption": caption,
        "markdown": str(published.get("markdown") or "").strip(),
    }


async def enrich_drafts_with_diagrams(
    drafts: List[dict],
    *,
    user_id: str,
    source_pack: dict,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> List[dict]:
    """Best-effort diagram enrichment for drafts (parallel, bounded)."""

    uid = str(user_id or "").strip() or "anonymous"
    sp = source_pack if isinstance(source_pack, dict) else {}
    subject = str(sp.get("subject") or "").strip()

    items: List[dict] = [dict(d) for d in (drafts or []) if isinstance(d, dict)]
    if not items:
        return []

    sem = asyncio.Semaphore(3)

    async def _enrich_one(d: dict) -> dict:
        existing = d.get("diagrams")
        if isinstance(existing, list) and any(isinstance(x, dict) and str(x.get("url") or "").strip() for x in existing):
            return d

        stem = str(d.get("stem") or "").strip()
        if not stem:
            return d

        # Fast heuristic gate to avoid pointless LLM calls.
        if not _heuristic_need_diagram(subject=subject, stem=stem):
            return d

        async with sem:
            try:
                decision = await assess_diagram_need(
                    d,
                    subject=subject,
                    stream_reasoning=stream_reasoning,
                    on_reasoning_event=on_reasoning_event,
                )
            except Exception:
                decision = {"need_diagram": True, "kind": "auto"}

            if not bool(decision.get("need_diagram")):
                return d

            diagram = await generate_question_diagram(
                d,
                subject=subject,
                user_id=uid,
                stream_reasoning=stream_reasoning,
                on_reasoning_event=on_reasoning_event,
            )
            if not diagram or not isinstance(diagram, dict) or not str(diagram.get("url") or "").strip():
                return d

            out = dict(d)
            out["diagrams"] = [diagram]
            return out

    results = await asyncio.gather(*[_enrich_one(d) for d in items], return_exceptions=True)
    out: List[dict] = []
    for base, r in zip(items, results):
        if isinstance(r, Exception):
            out.append(base)
        elif isinstance(r, dict):
            out.append(r)
        else:
            out.append(base)
    return out

