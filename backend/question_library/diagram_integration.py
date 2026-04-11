from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.core.settings import LESSON_PLAN_MODEL
from backend.llm.client import is_llm_configured
from backend.question_library.diagram_utils import render_asy_to_url, render_tikz_to_url
from backend.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.question_library.subject_knowledge import infer_subject_family
from backend.shared.diagrams.static_render import check_asy_tools, check_tikz_tools

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

    tikz_ok = len(check_tikz_tools()) == 0
    asy_ok = len(check_asy_tools()) == 0
    available_kinds = [k for k, ok in (("tikz", tikz_ok), ("asy", asy_ok)) if ok] + ["none"]

    # If LLM isn't available, rely on a conservative heuristic.
    if not is_llm_configured():
        return {"need_diagram": _heuristic_need_diagram(subject=subject, stem=stem), "kind": "auto", "reason": "heuristic"}

    fam = infer_subject_family(subject)
    payload: Dict[str, Any] = {
        "subject": str(subject or "").strip(),
        "subject_family": fam,
        "stem": _clip(stem, 1200),
        "available_kinds": available_kinds,
        "output_schema": {
            "need_diagram": "bool",
            "kind": "string (tikz|asy|none)",
            "reason": "string",
        },
    }

    system_content = (
        "<role>你是审题教研员，负责判断题目是否需要配图。</role>\n"
        "<rules>\n"
        "  <rule>只有当缺少配图会明显增加歧义或阅读难度，才 need_diagram=true。</rule>\n"
        "  <rule>配图后端收敛为静态矢量：优先 TikZ/PGF；仅当 TikZ 不适合或不可用时选 Asymptote。</rule>\n"
        "  <rule>kind 必须从 available_kinds 中选择；need_diagram=false 时 kind=none。</rule>\n"
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
    if kind not in set(available_kinds):
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
    tikz_ok = len(check_tikz_tools()) == 0
    asy_ok = len(check_asy_tools()) == 0
    available_kinds = [k for k, ok in (("tikz", tikz_ok), ("asy", asy_ok)) if ok]
    prefer = "tikz" if tikz_ok else "asy" if asy_ok else "none"

    if not is_llm_configured():
        # Without LLM, we can't reliably build a spec; return None.
        return None

    payload: Dict[str, Any] = {
        "subject": str(subject or "").strip(),
        "subject_family": fam,
        "preferred_kind": prefer,
        "available_kinds": available_kinds + ["none"],
        "stem": _clip(stem, 1400),
        "output_schema": {
            "need_diagram": "bool",
            "kind": "string (tikz|asy|none)",
            "alt": "string",
            "caption": "string",
            "tikz": "string (when kind=tikz; must include \\begin{tikzpicture}...\\end{tikzpicture})",
            "preamble": "string (optional when kind=tikz; appended to TeX preamble)",
            "asy": "string (when kind=asy; Asymptote code)",
        },
    }

    system_content = (
        "<role>你是一个题库配图工程师，负责为题目生成高质量静态矢量配图。</role>\n"
        "<rules>\n"
        "  <rule>只允许使用静态矢量后端：TikZ/PGF（首选）与 Asymptote（次选）。禁止选择其他后端。</rule>\n"
        "  <rule>kind 必须从 available_kinds 中选择；优先 TikZ，只有在 TikZ 不适合或不可用时才选 Asymptote。</rule>\n"
        "</rules>\n"
        "<constraints>\n"
        "  <rule>图必须服务于题意：标注关键点/方向/量，不要画装饰性内容。</rule>\n"
        "  <rule>若题目不需要图，need_diagram=false 并 kind=none。</rule>\n"
        "  <rule>所有坐标/标注必须在代码中明确，不要依赖隐含约定。</rule>\n"
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
    allowed = set(available_kinds + ["none"])
    if kind not in allowed:
        kind = prefer
    if kind == "none" or prefer == "none":
        return None

    alt = str(obj.get("alt") or "diagram").strip() or "diagram"
    caption = str(obj.get("caption") or "").strip()

    try:
        if kind == "asy":
            asy = str(obj.get("asy") or obj.get("asymptote") or "").strip()
            if not asy and "tikz" in available_kinds:
                kind = "tikz"
            else:
                published = await render_asy_to_url(asy=asy, user_id=user_id, alt=alt)

        if kind == "tikz":
            tikz = str(obj.get("tikz") or "").strip()
            if not tikz and "asy" in available_kinds:
                kind = "asy"
                asy = str(obj.get("asy") or obj.get("asymptote") or "").strip()
                published = await render_asy_to_url(asy=asy, user_id=user_id, alt=alt)
            else:
                preamble = str(obj.get("preamble") or "").strip()
                published = await render_tikz_to_url(tikz=tikz, user_id=user_id, alt=alt, preamble=preamble)
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
