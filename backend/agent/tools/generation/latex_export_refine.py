from __future__ import annotations

import json
import os
from typing import Any, Dict

from backend.agent.tools.utils.text_utils import _trim_overlap
from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger
from backend.llm.client import is_llm_configured
from backend.media.generated import default_generated_media_ttl_s, publish_generated_text

from backend.agent.tools.generation.latex_export_utils import (
    _auto_fix_latex,
    _clamp_int,
    _looks_incomplete_latex,
    _looks_truncated_latex_chunk,
    _normalize_latex_text,
)

logger = get_logger(__name__)


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
        try:
            ctx.working_memory["latex_tex"] = tex
        except Exception:
            logger.debug("latex_export_set_working_memory_failed", exc_info=True)

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

            try:
                ctx.working_memory["latex_tex"] = tex.strip() + "\n"
                ctx.working_memory["tex_url"] = url
                ctx.working_memory["tex_filename"] = filename
            except Exception:
                logger.debug("latex_export_set_working_memory_failed", exc_info=True)

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
                "下面是一份 LaTeX（ElegantBook）。请在不改变整体结构的前提下修订，使其更容易编译且排版更干净。",
                "只输出完整 LaTeX 源码（从 \\documentclass 到 \\end{document}），不要 Markdown 代码块，不要解释。",
                "修复常见问题：未转义的特殊字符（%, _, &, #）、未闭合的环境/括号、错误的图片扩展名（SVG 请改为文字占位而非 includegraphics）。",
                "数学公式保持原意，确保括号闭合。",
                "不要输出参考文献/URL 列表。",
                "如提供 compile_error，请优先修复该错误（缺包/缺文件/语法错误/未闭合环境等）。",
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
                {"role": "system", "content": "你是严谨的 LaTeX 修订助手，输出必须可编译。"},
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
                    "上一轮输出疑似被截断。请严格从 existing_latex_tail 的末尾继续补全剩余 LaTeX。",
                    "仅输出需要追加的 LaTeX，不要重复前文。",
                    "若 existing_latex_tail 的最后一行/公式/环境未结束，请先补齐闭合再继续。",
                    "最终必须包含完整可编译的 LaTeX（含 \\end{document}）。",
                ],
            }
            cont_res = await self._call_llm_response(
                messages=[
                    {"role": "system", "content": "你是严谨的 LaTeX 续写助手，只输出需要追加的内容，不要重复前文。"},
                    {"role": "user", "content": json.dumps(cont_prompt, ensure_ascii=False)},
                    {"role": "assistant", "content": tail},
                    {"role": "user", "content": "继续。只输出需要追加的 LaTeX，不要重复 existing_latex_tail。"},
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

        try:
            ctx.working_memory["latex_tex"] = refined.strip() + "\n"
            ctx.working_memory["tex_url"] = url
            ctx.working_memory["tex_filename"] = filename
        except Exception:
            logger.debug("latex_export_set_working_memory_failed", exc_info=True)

        return {"tex_url": url, "filename": filename, "sha256": sha, "bytes": size, "model": model}

