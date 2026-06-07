from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.core.settings import LESSON_PLAN_MODEL
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry
from backend.generation.question_library.diagram_utils import (
    render_asy_to_url,
    render_matplotlib_2d_to_url,
    render_tikz_to_url,
)
from backend.generation.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.generation.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.generation.question_library.subject_knowledge import infer_subject_family
from backend.generation.question_library.verify_diagram import verify_diagram_with_vision
from backend.shared.diagrams.static_render import check_asy_tools, check_tikz_tools

logger = get_logger(__name__)


def _diagram_need_system_prompt() -> str:
    return create_default_prompt_registry().render("question.diagram.need.v1").content


def _diagram_spec_system_prompt() -> str:
    return create_default_prompt_registry().render("question.diagram.spec.v1").content


_FUNCTION_GRAPH_KEYWORDS = (
    "函数图象", "函数图像", "图象", "图像", "y=", "y =",
    "f(x)", "f (x)", "g(x)", "曲线", "正弦曲线", "余弦曲线",
    "二次函数", "指数函数", "对数函数", "幂函数", "三角函数",
)


def _looks_like_function_graph(stem: str, subject_family: str) -> bool:
    """Whether the question stem suggests a function-plot rather than geometric figure.

    Used to decide when matplotlib_2d should appear in the available_kinds list."""

    if subject_family != "math":
        return False
    s = str(stem or "")
    return any(kw in s for kw in _FUNCTION_GRAPH_KEYWORDS)


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
    available_kinds = [k for k, ok in (("tikz", tikz_ok), ("asy", asy_ok)) if ok]
    # matplotlib_2d is available iff stem mentions function graphs; matplotlib is always installed.
    fam_early = infer_subject_family(subject)
    if _looks_like_function_graph(stem, fam_early):
        available_kinds.append("matplotlib_2d")
    available_kinds = available_kinds + ["none"]

    # If LLM isn't available, rely on a conservative heuristic.
    if not is_llm_configured():
        return {"need_diagram": _heuristic_need_diagram(subject=subject, stem=stem), "kind": "auto", "reason": "heuristic"}

    fam = fam_early
    payload: Dict[str, Any] = {
        "subject": str(subject or "").strip(),
        "subject_family": fam,
        "stem": _clip(stem, 1200),
        "available_kinds": available_kinds,
        "output_schema": {
            "need_diagram": "bool",
            "kind": "string (tikz|asy|matplotlib_2d|none)",
            "reason": "string",
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {"role": "system", "content": _diagram_need_system_prompt()},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.55,
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
    can_plot = _looks_like_function_graph(stem, fam)
    if can_plot:
        available_kinds.append("matplotlib_2d")
    prefer = "matplotlib_2d" if can_plot else ("tikz" if tikz_ok else "asy" if asy_ok else "none")

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
            "kind": "string (tikz|asy|matplotlib_2d|none)",
            "alt": "string",
            "caption": "string",
            "tikz": "string (when kind=tikz; must include \\begin{tikzpicture}...\\end{tikzpicture})",
            "preamble": "string (optional when kind=tikz; appended to TeX preamble)",
            "asy": "string (when kind=asy; Asymptote code)",
            "matplotlib_spec": {
                "x_range": "[number, number]",
                "y_range": "[number, number] (optional)",
                "title": "string (optional)",
                "curves": [{"expr": "string (python-like, variable=x)", "label": "string (optional)"}],
            },
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {"role": "system", "content": _diagram_spec_system_prompt()},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.65,
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

    published: Optional[Dict[str, Any]] = None
    try:
        if kind == "matplotlib_2d":
            spec = obj.get("matplotlib_spec")
            if not isinstance(spec, dict):
                # Fallback if LLM put curves at the root.
                spec = {"curves": obj.get("curves") or []}
            if not (spec.get("curves") or spec.get("expr")):
                # Couldn't build a usable spec; fall back to TikZ if available.
                if "tikz" in available_kinds:
                    kind = "tikz"
                elif "asy" in available_kinds:
                    kind = "asy"
                else:
                    return None
            else:
                published = await render_matplotlib_2d_to_url(spec=spec, user_id=user_id, alt=alt)

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
        logger.exception("question_library_diagram_render_failed", extra={"subject": subject})
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
        "cached": bool(published.get("cached")),
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
    verify_enabled = (os.getenv("QUESTION_LIBRARY_DIAGRAM_VERIFY") or "").strip().lower() in {"1", "true", "yes", "on"}
    verify_strictness = int(os.getenv("QUESTION_LIBRARY_DIAGRAM_VERIFY_STRICTNESS") or 3)

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
                logger.exception("question_library_diagram_decision_failed", extra={"subject": subject})
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

            # Best-effort vision verification (env-gated to avoid extra LLM cost by default).
            if verify_enabled:
                try:
                    verdict = await verify_diagram_with_vision(
                        diagram_url=str(diagram.get("url") or ""),
                        description=stem,
                        strictness=verify_strictness,
                    )
                    diagram["verification"] = {
                        "ok": bool(verdict.get("ok")),
                        "issues": list(verdict.get("issues") or [])[:5],
                        "repair_hint": str(verdict.get("repair_hint") or ""),
                        "confidence": float(verdict.get("confidence") or 0.0),
                        "mode": str(verdict.get("mode") or ""),
                    }
                except Exception:
                    logger.warning("question_library_diagram_verify_failed", exc_info=True)
                    diagram["verification"] = {"ok": False, "issues": ["verify_exception"], "mode": "error"}

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
