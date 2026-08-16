from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger
from backend.core.settings import model_name
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry

logger = get_logger(__name__)


def _draft_critique_system_prompt() -> str:
    return create_default_prompt_registry().render("agent.tool.draft_critique.v1").content


def _extract_points(args: Dict[str, Any], ctx: CompressedContext) -> List[str]:
    provided = args.get("knowledge_points")
    if isinstance(provided, list):
        pts = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if pts:
            return pts[:15]

    # As a critique tool, we prefer to infer from existing generated sections.
    mat = ctx.working_memory.get("generate_study_material") or ctx.working_memory.get("study_material") or {}
    if isinstance(mat, dict) and isinstance(mat.get("sections"), list):
        pts = [
            str(x.get("knowledge_point") or "").strip()
            for x in (mat.get("sections") or [])
            if isinstance(x, dict) and str(x.get("knowledge_point") or "").strip()
        ]
        if pts:
            # Dedup preserving order.
            seen = set()
            ordered = [x for x in pts if not (x in seen or seen.add(x))]
            return ordered[:15]

    topic = str(args.get("topic") or ctx.current_task or "").strip()
    return [topic] if topic else []


def _find_section(markdown_blob: Dict[str, Any], kp: str) -> Optional[Dict[str, Any]]:
    secs = markdown_blob.get("sections") if isinstance(markdown_blob.get("sections"), list) else []
    for s in secs:
        if not isinstance(s, dict):
            continue
        if str(s.get("knowledge_point") or "").strip() == kp:
            return s
    return None


def _outline_verify_items(ctx: CompressedContext, kp: str) -> List[str]:
    outlines = ctx.working_memory.get("outlines")
    outlines = dict(outlines) if isinstance(outlines, dict) else {}
    outline = outlines.get(kp) if isinstance(outlines.get(kp), dict) else {}
    sections = outline.get("sections") if isinstance(outline.get("sections"), list) else []
    checks: List[str] = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        verify = sec.get("verify")
        if isinstance(verify, list):
            for v in verify[:6]:
                s = str(v or "").strip()
                if s:
                    checks.append(s)
    # Cap: keep prompt compact.
    return checks[:18]


class SelfCritiqueToolsMixin:
    async def _tool_critique_draft(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Critique generated draft per knowledge point and provide actionable revision instructions.

        Writes:
        - ctx.working_memory["critiques"][knowledge_point] = critique_result (dict)
        """

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)  # type: ignore[attr-defined]

        points = _extract_points(args, ctx)
        material = ctx.working_memory.get("generate_study_material") or ctx.working_memory.get("study_material") or {}
        material = material if isinstance(material, dict) else {}

        knowledge_types = ctx.working_memory.get("knowledge_types")
        knowledge_types = dict(knowledge_types) if isinstance(knowledge_types, dict) else {}

        model = str(
            model_name("study_materials_critique")
            or getattr(getattr(self, "config", None), "reflector_model", "")
            or getattr(getattr(self, "config", None), "planner_model", "")
        ).strip()
        if not model:
            model = "gpt-4o-mini"

        try:
            threshold = float(
                args.get("threshold")
                or os.getenv("STUDY_MATERIALS_CRITIQUE_THRESHOLD")
                or os.getenv("STUDY_MATERIALS_REFINE_THRESHOLD")
                or "7.0"
            )
        except (TypeError, ValueError):
            threshold = 7.0
        threshold = max(0.0, min(threshold, 10.0))
        study_opts = ctx.working_memory.get("study_options")
        study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
        preset = str(args.get("preset") or study_opts.get("preset") or "standard").strip().lower() or "standard"
        if preset == "research":
            threshold = max(threshold, 8.0)

        async def _critique_one(kp: str) -> Dict[str, Any]:
            sec = _find_section(material, kp) or {}
            draft = str(sec.get("explanation_markdown") or "").strip()
            kt_obj = knowledge_types.get(kp) if isinstance(knowledge_types.get(kp), dict) else {}
            knowledge_type = str(kt_obj.get("knowledge_type") or "").strip().lower()
            verify_checks = _outline_verify_items(ctx, kp)

            if not draft:
                out = {
                    "knowledge_point": kp,
                    "score": 0.0,
                    "dimensions": {"accuracy": 0, "clarity": 0, "completeness": 0, "originality": 0, "depth_match": 0},
                    "issues": ["The explanation is empty or generation failed."],
                    "revision_instructions": ["Regenerate the core explanation covering definition, intuition, key properties, misconceptions, and application framework."],
                    "should_refine": True,
                    "threshold": threshold,
                    "source": "heuristic",
                }
                ctx.working_memory.setdefault("critiques", {})[kp] = out
                return out

            if not is_llm_configured():
                if strict_llm:
                    raise RuntimeError("llm_not_configured")
                # Heuristic: basic sanity checks only.
                score = 7.0
                if len(draft) < 400:
                    score = 5.0
                out = {
                    "knowledge_point": kp,
                    "score": score,
                    "dimensions": {},
                    "issues": [],
                    "revision_instructions": [],
                    "should_refine": bool(score < threshold),
                    "threshold": threshold,
                    "source": "heuristic",
                }
                ctx.working_memory.setdefault("critiques", {})[kp] = out
                return out

            prompt = {
                "topic": topic,
                "subject": subject,
                "knowledge_point": kp,
                "knowledge_type": knowledge_type,
                "verify_checks": verify_checks,
                "draft_markdown": draft,
                "requirements": [
                    "Review draft_markdown across multiple dimensions and provide executable revision instructions.",
                    "维度：准确性accuracy、清晰度clarity、完整性completeness、原创性originality、深度匹配depth_match（与 ability_score/知识类型匹配）。",
                    "issues must contain 3-10 items and be as specific as possible, identifying the section or expression type.",
                    "revision_instructions must contain 3-12 instructions directly executable by a writing model. Avoid vague advice.",
                    "Output strict JSON only: score(0~10), dimensions({...}), issues(string[]), revision_instructions(string[]).",
                    "Do not output URLs, reference sections, or evidence markers.",
                ],
            }

            raw = await self._call_llm_text(  # type: ignore[attr-defined]
                messages=[
                    {"role": "system", "content": _draft_critique_system_prompt()},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                model=model,
                temperature=0.15,
                max_tokens=1600,
                response_format={"type": "json_object"},
                raise_on_fail=strict_llm,
            )
            obj = self._extract_json_obj(raw)  # type: ignore[attr-defined]

            try:
                score = float(obj.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            score = max(0.0, min(score, 10.0))

            dims = obj.get("dimensions") if isinstance(obj.get("dimensions"), dict) else {}
            issues = obj.get("issues") if isinstance(obj.get("issues"), list) else []
            instr = obj.get("revision_instructions") if isinstance(obj.get("revision_instructions"), list) else []

            out = {
                "knowledge_point": kp,
                "score": score,
                "dimensions": dims,
                "issues": [str(x).strip() for x in issues if str(x).strip()][:12],
                "revision_instructions": [str(x).strip() for x in instr if str(x).strip()][:18],
                "should_refine": bool(score < threshold),
                "threshold": threshold,
                "source": "llm",
            }
            ctx.working_memory.setdefault("critiques", {})[kp] = out
            return out

        items = [await _critique_one(kp) for kp in points]
        return {"topic": topic, "subject": subject, "items": items}
