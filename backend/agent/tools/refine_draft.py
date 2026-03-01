from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from backend.agent.tools.text_utils import _sanitize_explanation_markdown
from backend.agent.types import CompressedContext
from backend.core.llm_client import is_llm_configured


def _extract_points(args: Dict[str, Any], ctx: CompressedContext) -> List[str]:
    provided = args.get("knowledge_points")
    if isinstance(provided, list):
        pts = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if pts:
            return pts[:15]

    critiques = ctx.working_memory.get("critiques")
    if isinstance(critiques, dict) and critiques:
        pts = [str(k or "").strip() for k in critiques.keys() if str(k or "").strip()]
        if pts:
            return pts[:15]

    topic = str(args.get("topic") or ctx.current_task or "").strip()
    return [topic] if topic else []


def _find_section(material: Dict[str, Any], kp: str) -> Optional[Dict[str, Any]]:
    secs = material.get("sections") if isinstance(material.get("sections"), list) else []
    for s in secs:
        if not isinstance(s, dict):
            continue
        if str(s.get("knowledge_point") or "").strip() == kp:
            return s
    return None


class RefineDraftToolsMixin:
    async def _tool_refine_draft(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Refine a draft according to critique instructions (targeted revision, not full rewrite).

        This tool is safe to run unconditionally; it will no-op when critique score >= threshold.

        Side effects:
        - Patches ctx.working_memory["generate_study_material"].sections[...].explanation_markdown for the kp.
        """

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)  # type: ignore[attr-defined]

        try:
            threshold = float(
                args.get("threshold")
                or os.getenv("STUDY_MATERIALS_CRITIQUE_SKIP_THRESHOLD")
                or os.getenv("STUDY_MATERIALS_REFINE_THRESHOLD")
                or os.getenv("STUDY_MATERIALS_CRITIQUE_THRESHOLD")
                or "7.0"
            )
        except Exception:
            threshold = 7.0
        threshold = max(0.0, min(threshold, 10.0))
        try:
            study_opts = ctx.working_memory.get("study_options")
            study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
            preset = str(args.get("preset") or study_opts.get("preset") or "standard").strip().lower() or "standard"
            # In research mode, be stricter: don't skip refine unless score is very high.
            if preset == "research":
                threshold = max(threshold, 8.5)
        except Exception:
            pass

        points = _extract_points(args, ctx)
        critiques = ctx.working_memory.get("critiques")
        critiques = dict(critiques) if isinstance(critiques, dict) else {}

        material = ctx.working_memory.get("generate_study_material") or ctx.working_memory.get("study_material") or {}
        material = material if isinstance(material, dict) else {}

        model = str(
            os.getenv("STUDY_MATERIALS_REFINER_MODEL")
            or os.getenv("STUDY_MATERIALS_WRITER_MODEL")
            or getattr(getattr(self, "config", None), "planner_model", "")
        ).strip()
        if not model:
            model = "gpt-4o-mini"

        async def _refine_one(kp: str) -> Dict[str, Any]:
            critique = critiques.get(kp) if isinstance(critiques.get(kp), dict) else {}
            try:
                score = float(critique.get("score") or 0.0)
            except Exception:
                score = 0.0
            score = max(0.0, min(score, 10.0))
            instructions = critique.get("revision_instructions")
            instructions_list = [str(x).strip() for x in instructions if str(x).strip()] if isinstance(instructions, list) else []

            if score >= threshold or not instructions_list:
                return {
                    "knowledge_point": kp,
                    "skipped": True,
                    "reason": "score_ok_or_no_instructions",
                    "score": score,
                    "threshold": threshold,
                }

            sec = _find_section(material, kp) or {}
            draft = str(sec.get("explanation_markdown") or "").strip()
            if not draft:
                return {"knowledge_point": kp, "skipped": True, "reason": "no_draft", "score": score, "threshold": threshold}

            if not is_llm_configured():
                if strict_llm:
                    raise RuntimeError("llm_not_configured")
                return {
                    "knowledge_point": kp,
                    "skipped": True,
                    "reason": "llm_not_configured",
                    "score": score,
                    "threshold": threshold,
                }

            prompt = {
                "topic": topic,
                "subject": subject,
                "knowledge_point": kp,
                "score_before": score,
                "threshold": threshold,
                "revision_instructions": instructions_list[:16],
                "draft_markdown": draft,
                "requirements": [
                    "请根据 revision_instructions 对 draft_markdown 做定向修订（不要整篇重写）。",
                    "保持整体结构与小节标题（#### ...）尽量稳定；只在必要处增删小段落/要点。",
                    "修复：遗漏前提/条件、逻辑断裂、表述不清、概念混淆、过于空泛等问题。",
                    "严禁输出 URL/参考资料段落/证据标记；数学公式用 $...$ / $$...$$。",
                    "只输出修订后的 Markdown（不要解释，不要 JSON）。",
                ],
            }

            revised = await self._call_llm_text(  # type: ignore[attr-defined]
                messages=[
                    {"role": "system", "content": "你是严谨的 Markdown 编辑，只输出修订后的 Markdown。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                model=model,
                temperature=0.2,
                max_tokens=8000,
                raise_on_fail=strict_llm,
            )
            revised_md = _sanitize_explanation_markdown(str(revised or ""), knowledge_point=kp)
            if not revised_md:
                return {"knowledge_point": kp, "skipped": True, "reason": "empty_revision", "score": score, "threshold": threshold}

            # Patch the canonical material so downstream assemble/export stays compatible.
            try:
                gen = ctx.working_memory.get("generate_study_material")
                if isinstance(gen, dict) and isinstance(gen.get("sections"), list):
                    for s in gen.get("sections") or []:
                        if not isinstance(s, dict):
                            continue
                        if str(s.get("knowledge_point") or "").strip() != kp:
                            continue
                        s["explanation_markdown"] = revised_md
                        s["explanation_source"] = "llm_refined"
                        s["refine_score_before"] = score
                        s["refine_threshold"] = threshold
                        break
            except Exception:
                pass

            return {
                "knowledge_point": kp,
                "refined": True,
                "score_before": score,
                "threshold": threshold,
                "markdown_chars": len(revised_md),
            }

        items = [await _refine_one(kp) for kp in points]
        return {"topic": topic, "subject": subject, "items": items}
