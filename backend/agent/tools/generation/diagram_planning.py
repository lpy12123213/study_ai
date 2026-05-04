from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, List

from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger
from backend.llm.client import is_llm_configured

logger = get_logger(__name__)


def _has_tool(name: str) -> bool:
    return bool(shutil.which(str(name or "").strip()))


def _tikz_available() -> bool:
    # TikZ -> SVG requires both tools.
    return _has_tool("xelatex") and _has_tool("dvisvgm")


def _asy_available() -> bool:
    return _has_tool("asy")


def _seedream_available() -> bool:
    api_key = str(os.getenv("ARK_API_KEY") or os.getenv("ARK_API") or "").strip()
    model = str(
        os.getenv("SEEDREAM_MODEL") or os.getenv("ARK_IMAGE_MODEL") or os.getenv("ARK_IMAGES_MODEL") or ""
    ).strip()
    return bool(api_key and model)


def _extract_points(args: Dict[str, Any], ctx: CompressedContext) -> List[str]:
    provided = args.get("knowledge_points")
    if isinstance(provided, list):
        pts = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if pts:
            return pts[:15]

    split_res = ctx.working_memory.get("split_knowledge_points")
    if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
        pts = [str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()]
        if pts:
            return pts[:15]

    topic = str(args.get("topic") or ctx.current_task or "").strip()
    return [topic] if topic else []


def _existing_diagrams(ctx: CompressedContext, kp: str) -> List[Dict[str, Any]]:
    blob = ctx.working_memory.get("diagrams")
    if not isinstance(blob, dict):
        return []
    entries: List[Dict[str, Any]] = []
    if isinstance(blob.get("items"), list):
        entries = [x for x in (blob.get("items") or []) if isinstance(x, dict)]
    elif isinstance(blob.get("sections"), list):
        entries = [x for x in (blob.get("sections") or []) if isinstance(x, dict)]
    for it in entries:
        if str(it.get("knowledge_point") or "").strip() != kp:
            continue
        ds = it.get("diagrams")
        if isinstance(ds, list):
            return [d for d in ds if isinstance(d, dict)]
        return []
    return []


class DiagramPlanningToolsMixin:
    async def _tool_generate_diagrams(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Generate teaching diagrams for knowledge points (plan -> render -> persist).

        Notes:
        - This tool is best-effort: diagram failures must not abort the whole study generation.
        - Uses source briefs when available; falls back to lightweight prompts.
        """

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        points = _extract_points(args, ctx)

        # Keep strict_llm for compatibility / telemetry, but do NOT let it raise here.
        strict_llm = self._strict_llm(ctx, args)  # type: ignore[attr-defined]

        study_opts = ctx.working_memory.get("study_options")
        study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
        preset = str(args.get("preset") or study_opts.get("preset") or "standard").strip().lower() or "standard"
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = "standard"

        default_max = 1 if preset == "quick" else 2 if preset == "standard" else 3 if preset == "deep" else 4
        max_diagrams = int(args.get("max_diagrams") or default_max)
        max_diagrams = max(0, min(max_diagrams, 12))

        model = str(
            os.getenv("STUDY_MATERIALS_DIAGRAM_PLANNER_MODEL")
            or getattr(getattr(self, "config", None), "summarizer_model", "")
            or getattr(getattr(self, "config", None), "planner_model", "")
        ).strip()
        if not model:
            model = "gpt-4o-mini"

        source_briefs = ctx.working_memory.get("source_briefs")
        source_briefs = dict(source_briefs) if isinstance(source_briefs, dict) else {}

        tikz_ok = _tikz_available()
        asy_ok = _asy_available()
        seedream_ok = _seedream_available()
        allowed_kinds: List[str] = []
        if tikz_ok:
            allowed_kinds.append("tikz_to_svg")
        if asy_ok:
            allowed_kinds.append("asy_to_svg")
        # Only expose the Matplotlib backend when TeX-based static renderers are unavailable.
        if not allowed_kinds:
            allowed_kinds.append("draw_diagram")
        if seedream_ok:
            allowed_kinds.append("seedream_generate")

        async def _gen_one(kp: str) -> Dict[str, Any]:
            existing = _existing_diagrams(ctx, kp)
            need = max(0, max_diagrams - len(existing))
            if need <= 0:
                return {
                    "knowledge_point": kp,
                    "skipped": True,
                    "reason": "already_have_diagrams",
                    "existing": len(existing),
                }

            if not is_llm_configured():
                return {
                    "knowledge_point": kp,
                    "skipped": True,
                    "reason": "llm_not_configured",
                    "existing": len(existing),
                }

            brief = source_briefs.get(kp) if isinstance(source_briefs.get(kp), dict) else {}

            prompt = {
                "topic": topic,
                "subject": subject,
                "knowledge_point": kp,
                "preset": preset,
                "source_brief": brief,
                "capabilities": {
                    "allowed_kinds": allowed_kinds,
                    "tikz_available": tikz_ok,
                    "asy_available": asy_ok,
                    "seedream_available": seedream_ok,
                },
                "requirements": (
                    [
                        f"Generate up to {need} teaching diagrams for the knowledge point: {kp}.",
                        'Output STRICT JSON only: {"diagrams":[...]} (or {"diagrams":[]}).',
                        f"Allowed kinds: {', '.join(allowed_kinds)}.",
                    ]
                    + (
                        [
                            "Prefer `tikz_to_svg` (static vector, TikZ/PGF). Use `asy_to_svg` only when TikZ is unavailable or not suitable.",
                        ]
                        if "tikz_to_svg" in allowed_kinds
                        else ["Prefer `asy_to_svg` (static vector, Asymptote)."]
                        if "asy_to_svg" in allowed_kinds
                        else ["Use `draw_diagram` as a pure-Python fallback (Matplotlib)."]
                    )
                    + (["Use `seedream_generate` only when available and only as a last resort."] if seedream_ok else [])
                    + [
                        "Each diagram must include: kind, alt, caption.",
                    ]
                    + (
                        [
                            "draw_diagram: provide `spec` compatible with backend.core.plot_tools.render_schematic.",
                            "  - spec supports: title, objects[{id,shape,pos,label,size,color,fill}], wires[[[x,y],[x,y]]], forces[{object,direction,length,label}], annotations[{text,x,y,arrow_to}]",
                            "  - Keep it simple; do not overfit; no URLs.",
                        ]
                        if "draw_diagram" in allowed_kinds
                        else []
                    )
                    + (
                        [
                            "tikz_to_svg: provide `tikz` (must include \\begin{tikzpicture}...\\end{tikzpicture}) and optional `preamble`.",
                        ]
                        if "tikz_to_svg" in allowed_kinds
                        else []
                    )
                    + (
                        [
                            "asy_to_svg: provide `asy` (Asymptote code). Keep it static; no animations.",
                        ]
                        if "asy_to_svg" in allowed_kinds
                        else []
                    )
                    + (
                        [
                            "seedream_generate: provide `prompt` and optional `size` (default 1024x1024) and `n` (default 1).",
                        ]
                        if "seedream_generate" in allowed_kinds
                        else []
                    )
                    + [
                        "Do NOT output URLs or cite sources.",
                    ]
                ),
            }

            try:
                raw = await self._call_llm_text(  # type: ignore[attr-defined]
                    messages=[
                        {"role": "system", "content": "You are a teaching diagram helper. Output JSON only."},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                    model=model,
                    temperature=0.2,
                    max_tokens=1400,
                    response_format={"type": "json_object"},
                    # Non-fatal: never raise and let the main study flow continue.
                    raise_on_fail=False,
                )
            except Exception as exc:
                logger.warning("diagram_planner_failed", exc_info=True)
                msg = str(exc or "").strip().replace("\n", " ")
                msg = msg[:260]
                return {
                    "knowledge_point": kp,
                    "created": 0,
                    "diagrams": [],
                    "existing": len(existing),
                    "max_diagrams": max_diagrams,
                    "error": f"diagram_planner_failed: {msg}",
                    "strict_llm": bool(strict_llm),
                }

            obj = self._extract_json_obj(raw)  # type: ignore[attr-defined]
            diagrams_field = obj.get("diagrams") if isinstance(obj, dict) else None
            specs = (
                [x for x in (diagrams_field or []) if isinstance(x, dict)] if isinstance(diagrams_field, list) else []
            )
            specs = specs[:need]

            created: List[Dict[str, Any]] = []
            errors: List[str] = []

            for spec in specs:
                kind = str(spec.get("kind") or "").strip().lower()
                if kind in {"tikz", "latex", "tikzpicture", "tikz_picture"}:
                    kind = "tikz_to_svg"
                if kind in {"asy", "asymptote"}:
                    kind = "asy_to_svg"
                if kind in {"seedream", "image", "text2img", "t2i"}:
                    kind = "seedream_generate"
                if kind in {"draw", "schematic", "matplotlib", "mpl"}:
                    kind = "draw_diagram"

                if kind not in {"draw_diagram", "tikz_to_svg", "asy_to_svg", "seedream_generate"}:
                    # Heuristic: infer based on available fields.
                    if isinstance(spec.get("spec"), dict) or isinstance(spec.get("objects"), list):
                        kind = "draw_diagram"
                    elif str(spec.get("tikz") or "").strip():
                        kind = "tikz_to_svg"
                    elif str(spec.get("asy") or spec.get("asymptote") or "").strip():
                        kind = "asy_to_svg"
                    elif str(spec.get("prompt") or "").strip():
                        kind = "seedream_generate"
                    else:
                        kind = "draw_diagram"

                if kind not in allowed_kinds:
                    kind = allowed_kinds[0] if allowed_kinds else "draw_diagram"

                alt = str(spec.get("alt") or kp).strip() or kp
                caption = str(spec.get("caption") or "").strip()

                try:
                    if kind == "seedream_generate":
                        if not seedream_ok:
                            continue
                        prompt_text = str(spec.get("prompt") or "").strip()
                        if not prompt_text:
                            continue
                        res = await self._tool_seedream_generate(  # type: ignore[attr-defined]
                            {
                                "knowledge_point": kp,
                                "alt": alt,
                                "caption": caption,
                                "prompt": prompt_text,
                                "size": str(spec.get("size") or "1024x1024"),
                                "n": int(spec.get("n") or 1),
                            },
                            ctx,
                        )
                        if isinstance(res, dict) and res.get("success") and isinstance(res.get("diagram"), dict):
                            created.append(dict(res.get("diagram") or {}))
                        if isinstance(res, dict) and res.get("success") and isinstance(res.get("diagrams"), list):
                            created.extend([x for x in (res.get("diagrams") or []) if isinstance(x, dict)][:8])
                        continue

                    if kind == "tikz_to_svg":
                        if not tikz_ok:
                            continue
                        tikz_code = str(spec.get("tikz") or "").strip()
                        if not tikz_code:
                            continue
                        res = await self._tool_tikz_to_svg(  # type: ignore[attr-defined]
                            {
                                "knowledge_point": kp,
                                "alt": alt,
                                "caption": caption,
                                "tikz": tikz_code,
                                "preamble": str(spec.get("preamble") or ""),
                            },
                            ctx,
                        )
                        if isinstance(res, dict) and res.get("success") and isinstance(res.get("diagram"), dict):
                            created.append(dict(res.get("diagram") or {}))
                        continue

                    if kind == "asy_to_svg":
                        if not asy_ok:
                            continue
                        asy_code = str(spec.get("asy") or spec.get("asymptote") or "").strip()
                        if not asy_code:
                            continue
                        res = await self._tool_asy_to_svg(  # type: ignore[attr-defined]
                            {"knowledge_point": kp, "alt": alt, "caption": caption, "asy": asy_code},
                            ctx,
                        )
                        if isinstance(res, dict) and res.get("success") and isinstance(res.get("diagram"), dict):
                            created.append(dict(res.get("diagram") or {}))
                        continue

                    # draw_diagram (pure python / Matplotlib schematic)
                    spec_obj = spec.get("spec")
                    if not isinstance(spec_obj, dict):
                        spec_obj = {k: v for k, v in spec.items() if k not in {"kind", "alt", "caption"}}
                    if not spec_obj:
                        continue
                    res = await self._tool_draw_diagram(  # type: ignore[attr-defined]
                        {"knowledge_point": kp, "alt": alt, "caption": caption, "spec": spec_obj},
                        ctx,
                    )
                    if isinstance(res, dict) and res.get("success") and isinstance(res.get("diagram"), dict):
                        created.append(dict(res.get("diagram") or {}))
                except Exception as exc:  # pragma: no cover (best-effort)
                    logger.warning("diagram_generation_item_failed", exc_info=True)
                    msg = str(exc or "").strip().replace("\n", " ")
                    if msg:
                        errors.append(msg[:180])

            return {
                "knowledge_point": kp,
                "created": len(created),
                "diagrams": created[:8],
                "existing": len(existing),
                "max_diagrams": max_diagrams,
                "errors": errors[:6],
                "strict_llm": bool(strict_llm),
            }

        items = [await _gen_one(kp) for kp in points]
        ctx.working_memory["diagram_generation_report"] = {
            "topic": topic,
            "subject": subject,
            "preset": preset,
            "allowed_kinds": allowed_kinds,
            "tikz_available": tikz_ok,
            "asy_available": asy_ok,
            "seedream_available": seedream_ok,
            "items": [
                {
                    "knowledge_point": it.get("knowledge_point"),
                    "created": it.get("created"),
                    "error": it.get("error"),
                }
                for it in items
                if isinstance(it, dict)
            ],
        }
        return {"topic": topic, "subject": subject, "items": items, "allowed_kinds": allowed_kinds}
