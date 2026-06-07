from __future__ import annotations

import json
import os
from typing import Any, Dict

from backend.agent.tools.generation.latex_export_utils import (
    _auto_fix_latex,
    _clamp_int,
    _looks_incomplete_latex,
    _looks_truncated_latex_chunk,
    _normalize_latex_text,
)
from backend.agent.tools.utils.text_utils import _trim_overlap
from backend.agent.types import CompressedContext
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry
from backend.media.generated import default_generated_media_ttl_s, publish_generated_text


def _latex_refine_system_prompt() -> str:
    return create_default_prompt_registry().render("study.latex.refine.v1").content


def _latex_refine_continuation_system_prompt() -> str:
    return create_default_prompt_registry().render("study.latex.refine_continuation.v1").content


class LatexRefineMixin:
    async def _tool_refine_latex(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """对 LaTeX 做二次修订，尽量减少编译失败与排版问题。"""

        topic = str(args.get("topic") or ctx.current_task).strip() or "study_archive"
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        # LaTeX refining is LLM-dependent; fail fast to avoid cascading "latex_missing" errors.
        if not is_llm_configured():
            raise RuntimeError("llm_not_configured")

        tex = args.get("latex")
        if not isinstance(tex, str) or not tex.strip():
            tex = str(ctx.working_memory.get("latex_tex") or "").strip()
        if not tex:
            raise ValueError("latex_missing")

        tex = _auto_fix_latex(tex).strip() + "\n"
        ctx.working_memory["latex_tex"] = tex

        compile_error = str(args.get("compile_error") or "").strip()
        if len(compile_error) > 1800:
            compile_error = compile_error[:1799].rstrip() + "…"

        always_refine_raw = str(os.getenv("STUDY_MATERIALS_LATEX_ALWAYS_REFINE") or "0").strip().lower()
        always_refine = always_refine_raw in {"1", "true", "yes", "y", "on"}
        if (not compile_error) and (not always_refine):
            user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
            published = await publish_generated_text(
                tex.strip() + "\n",
                user_id=user_id,
                ext=".tex",
                file_type="tex",
                mime_type="application/x-tex; charset=utf-8",
                ttl_s=default_generated_media_ttl_s(),
            )
            sha = str(published.get("sha256") or "")
            filename = str(published.get("filename") or "")
            url = str(published.get("url") or "")
            size = int(published.get("bytes") or 0)

            ctx.working_memory["latex_tex"] = tex.strip() + "\n"
            ctx.working_memory["tex_url"] = url
            ctx.working_memory["tex_filename"] = filename

            return {"tex_url": url, "filename": filename, "sha256": sha, "bytes": size, "model": ""}

        model = str(
            os.getenv("STUDY_MATERIALS_LATEX_REFINE_MODEL")
            or os.getenv("STUDY_MATERIALS_LATEX_MODEL")
            or self.config.summarizer_model
            or self.config.planner_model
        ).strip()
        if not model:
            model = self.config.summarizer_model or self.config.planner_model
        reasoning_cfg = {"effort": "minimal", "exclude": True}
        prompt = {
            "topic": topic,
            "subject": subject,
            "requirements": [
                "Below is an ElegantBook LaTeX document. Revise it without changing the overall structure so it compiles more reliably and has cleaner typesetting.",
                "Output only complete LaTeX source from \\documentclass to \\end{document}. Do not output Markdown code fences or explanations.",
                "Fix common issues: unescaped special characters (%, _, &, #), unclosed environments/brackets, and invalid image extensions. For SVG, use a text placeholder instead of includegraphics.",
                "数学公式保持原意，确保括号闭合。",
                "Do not output references or URL lists.",
                "If compile_error is provided, prioritize fixing that error, such as missing package/file, syntax error, or unclosed environment.",
            ],
            "latex": tex,
            "compile_error": compile_error,
        }

        refine_max_tokens = _clamp_int(
            os.getenv("STUDY_MATERIALS_LATEX_REFINE_MAX_TOKENS")
            or os.getenv("STUDY_MATERIALS_LATEX_MAX_TOKENS")
            or 8000,
            default=8000,
            min_value=1200,
            max_value=20000,
        )
        res = await self._call_llm_response(
            messages=[
                {"role": "system", "content": _latex_refine_system_prompt()},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=model,
            temperature=0.2,
            max_tokens=refine_max_tokens,
            reasoning=reasoning_cfg,
            raise_on_fail=True,
        )
        refined = _normalize_latex_text(str(res.get("content") or "").strip())
        finish_reason = str(res.get("finish_reason") or "").strip().lower()
        usage = res.get("usage") if isinstance(res.get("usage"), dict) else {}
        if not refined:
            raise RuntimeError("llm_empty_response")

        if refined.startswith("```"):
            first_newline = refined.find("\n")
            if first_newline != -1:
                refined = refined[first_newline + 1 :]
            if refined.endswith("```"):
                refined = refined[:-3]
            refined = refined.strip()

        conts = 0
        max_continuations = _clamp_int(
            os.getenv("STUDY_MATERIALS_LATEX_REFINE_MAX_CONTINUATIONS")
            or os.getenv("STUDY_MATERIALS_LATEX_MAX_CONTINUATIONS")
            or 2,
            default=2,
            min_value=0,
            max_value=8,
        )
        while (
            conts < max_continuations
            and refined
            and (
                _looks_truncated_latex_chunk(refined, finish_reason, usage, max_tokens=refine_max_tokens)
                or _looks_incomplete_latex(refined)
            )
        ):
            tail = refined[-2000:]
            cont_prompt = {
                "topic": topic,
                "subject": subject,
                "compile_error": compile_error,
                "existing_latex_tail": tail,
                "instructions": [
                    "The previous output appears truncated. Continue the remaining LaTeX strictly from the end of existing_latex_tail.",
                    "Output only LaTeX that must be appended. Do not repeat previous content.",
                    "If the last line, formula, or environment in existing_latex_tail is unfinished, close it first and then continue.",
                    "The final result must contain complete compilable LaTeX, including \\end{document}.",
                ],
            }
            cont_res = await self._call_llm_response(
                messages=[
                    {"role": "system", "content": _latex_refine_continuation_system_prompt()},
                    {"role": "user", "content": json.dumps(cont_prompt, ensure_ascii=False)},
                    {"role": "assistant", "content": tail},
                    {"role": "user", "content": "Continue. Output only LaTeX that must be appended, and do not repeat existing_latex_tail."},
                ],
                model=model,
                temperature=0.2,
                max_tokens=refine_max_tokens,
                reasoning=reasoning_cfg,
                raise_on_fail=True,
            )
            addition = _normalize_latex_text(str(cont_res.get("content") or "").strip())
            finish_reason = str(cont_res.get("finish_reason") or "").strip().lower()
            usage = cont_res.get("usage") if isinstance(cont_res.get("usage"), dict) else {}
            if not addition:
                break
            addition = _trim_overlap(refined, addition)
            if not addition.strip():
                break
            if not refined.endswith("\n"):
                refined = refined + "\n"
            refined = (refined + addition).rstrip()
            conts += 1

        refined = _auto_fix_latex(refined).strip()

        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await publish_generated_text(
            refined.strip() + "\n",
            user_id=user_id,
            ext=".tex",
            file_type="tex",
            mime_type="application/x-tex; charset=utf-8",
            ttl_s=default_generated_media_ttl_s(),
        )
        sha = str(published.get("sha256") or "")
        filename = str(published.get("filename") or "")
        url = str(published.get("url") or "")
        size = int(published.get("bytes") or 0)

        ctx.working_memory["latex_tex"] = refined.strip() + "\n"
        ctx.working_memory["tex_url"] = url
        ctx.working_memory["tex_filename"] = filename

        return {"tex_url": url, "filename": filename, "sha256": sha, "bytes": size, "model": model}
