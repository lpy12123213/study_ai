from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from backend.agent.types import CompressedContext
from backend.core.settings import LESSON_PLAN_API_KEY, MOONSHOT_API_KEY


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

        Uses source briefs when available; falls back to lightweight prompts.
        """

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)  # type: ignore[attr-defined]

        points = _extract_points(args, ctx)

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

        async def _gen_one(kp: str) -> Dict[str, Any]:
            existing = _existing_diagrams(ctx, kp)
            need = max(0, max_diagrams - len(existing))
            if need <= 0:
                return {"knowledge_point": kp, "skipped": True, "reason": "already_have_diagrams", "existing": len(existing)}

            if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                if strict_llm:
                    raise RuntimeError("llm_not_configured")
                return {"knowledge_point": kp, "skipped": True, "reason": "llm_not_configured", "existing": len(existing)}

            brief = source_briefs.get(kp) if isinstance(source_briefs.get(kp), dict) else {}

            prompt = {
                "topic": topic,
                "subject": subject,
                "knowledge_point": kp,
                "preset": preset,
                "source_brief": brief,
                "requirements": [
                    f"请为知识点「{kp}」生成最多 {need} 张教学配图方案（JSON），用于帮助理解。",
                    "输出严格 JSON：{\"diagrams\":[...]}，若不需要画图输出 {\"diagrams\":[]}。",
                    "每个 diagram 需包含 kind(tikz_to_svg|seedream_generate), alt, caption。",
                    "tikz_to_svg：提供 tikz(必须，含 \\begin{tikzpicture}...\\end{tikzpicture})，可选 preamble(\\usetikzlibrary{...})。",
                    "seedream_generate：提供 prompt(必须)，可选 size(默认1024x1024) 与 n(默认1)。",
                    "优先 tikz_to_svg（线稿/示意图）；只有不适合线稿时再用 seedream_generate。",
                    "TikZ 避免复杂依赖（不要 pgfplots），尽量基础几何/流程/坐标示意。",
                    "严禁输出 URL 或引用来源原文。",
                ],
            }

            raw = await self._call_llm_text(  # type: ignore[attr-defined]
                messages=[
                    {"role": "system", "content": "你是教学绘图助手，只输出 JSON。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                model=model,
                temperature=0.2,
                max_tokens=1200,
                response_format={"type": "json_object"},
                raise_on_fail=strict_llm,
            )
            obj = self._extract_json_obj(raw)  # type: ignore[attr-defined]
            diagrams_field = obj.get("diagrams") if isinstance(obj, dict) else None
            specs = [x for x in (diagrams_field or []) if isinstance(x, dict)] if isinstance(diagrams_field, list) else []
            specs = specs[:need]

            created: List[Dict[str, Any]] = []
            for spec in specs:
                kind = str(spec.get("kind") or "").strip().lower()
                if kind in {"tikz", "latex", "tikzpicture", "tikz_picture"}:
                    kind = "tikz_to_svg"
                if kind in {"seedream", "image", "text2img", "t2i"}:
                    kind = "seedream_generate"
                if kind not in {"tikz_to_svg", "seedream_generate"}:
                    # Heuristic: pick based on presence of tikz/prompt.
                    if str(spec.get("tikz") or "").strip():
                        kind = "tikz_to_svg"
                    else:
                        kind = "seedream_generate"

                alt = str(spec.get("alt") or kp).strip() or kp
                caption = str(spec.get("caption") or "").strip()

                if kind == "seedream_generate":
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

            return {
                "knowledge_point": kp,
                "created": len(created),
                "diagrams": created[:8],
                "existing": len(existing),
                "max_diagrams": max_diagrams,
            }

        items = [await _gen_one(kp) for kp in points]
        return {"topic": topic, "subject": subject, "items": items}

