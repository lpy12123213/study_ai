from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, List

from backend.agent.tools.generation.latex_export_utils import (
    _auto_fix_latex,
    _clamp_int,
    _extract_latex_body,
    _looks_incomplete_latex,
    _looks_truncated_latex_chunk,
    _normalize_latex_text,
)
from backend.agent.tools.utils.text_utils import _trim_overlap
from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger
from backend.core.settings import STUDY_MATERIALS_WRITER_MODEL
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry
from backend.media.generated import default_generated_media_ttl_s, publish_generated_text

logger = get_logger(__name__)


def _latex_convert_system_prompt() -> str:
    return create_default_prompt_registry().render("study.latex.convert.v1").content


def _latex_convert_continuation_system_prompt() -> str:
    return create_default_prompt_registry().render("study.latex.convert_continuation.v1").content


class LatexConvertMixin:
    async def _tool_convert_markdown_to_latex(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """用 LLM 把 Markdown 转成 ElegantBook LaTeX，并发布为可下载 .tex。"""

        topic = str(args.get("topic") or ctx.current_task).strip() or "study_archive"
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        # LaTeX export is 100% LLM-dependent; fail fast even if other tools allow fallbacks.
        if not is_llm_configured():
            raise RuntimeError("llm_not_configured")

        markdown = args.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            markdown = str(ctx.working_memory.get("markdown") or "").strip()
        if not markdown:
            markdown = str(ctx.working_memory.get("assemble_study_archive") or "").strip()
        if not markdown:
            raise ValueError("markdown_empty")

        await self._emit_progress(percent=5, stage="解析 Markdown")

        model = str(
            os.getenv("STUDY_MATERIALS_LATEX_MODEL")
            or STUDY_MATERIALS_WRITER_MODEL
            or self.config.summarizer_model
            or self.config.planner_model
        ).strip()
        if not model:
            model = self.config.summarizer_model or self.config.planner_model
        title = f"自学材料：{topic}"
        if subject and subject not in title:
            title = f"{subject}｜{title}"

        template = (
            r"\documentclass[lang=cn]{elegantbook}"
            "\n"
            r"\usepackage{amsmath,amssymb}"
            "\n"
            r"\usepackage{graphicx}"
            "\n"
            r"\usepackage{hyperref}"
            "\n"
            r"\usepackage{booktabs,longtable}"
            "\n"
            r"\usepackage{xcolor}"
            "\n"
            r"\hypersetup{colorlinks=true,linkcolor=blue,urlcolor=blue}"
            "\n"
            r"\title{" + title.replace("{", "\\{").replace("}", "\\}") + r"}"
            "\n"
            r"\author{}"
            "\n"
            r"\date{\today}"
            "\n"
            r"\begin{document}"
            "\n"
            r"\pagenumbering{arabic}"
            "\n"
            r"\setcounter{page}{1}"
            "\n"
            r"\maketitle"
            "\n\n"
            r"% --- BEGIN_BODY ---"
            "\n"
            r"<BODY>"
            "\n"
            r"% --- END_BODY ---"
            "\n\n"
            r"\end{document}"
            "\n"
        )

        prompt = {
            "topic": topic,
            "subject": subject,
            "template": template,
            "requirements": [
                "Convert the Markdown below to LaTeX using the ElegantBook template.",
                "Output only LaTeX source. Do not output Markdown code fences or extra explanation.",
                "Output only the body LaTeX used to replace <BODY>. Do not output documentclass, preamble, \\begin{document}, \\end{document}, \\maketitle, % --- BEGIN_BODY ---, or % --- END_BODY ---.",
                "Use LaTeX structure for the body: Markdown headings #/##/###/#### map to \\section/\\subsection/\\subsubsection/\\paragraph.",
                "保留数学公式 $...$ 与 $$...$$，确保括号与环境闭合。",
                "列表用 itemize/enumerate；代码块用 verbatim；表格必要时可简化。",
                "Images: handle only PNG/JPG/JPEG/WebP/GIF/BMP. Convert `![](/api/media/generated/xxx.png)` to `\\\\includegraphics[width=0.9\\\\linewidth]{xxx.png}`. For SVG images, do not insert graphics; replace with one sentence: `(Figure omitted: see SVG in the Markdown version)`.",
                "Do not output references, external links, or URL lists.",
            ],
            "markdown": markdown,
        }

        max_tokens = _clamp_int(
            os.getenv("STUDY_MATERIALS_LATEX_MAX_TOKENS") or 8000,
            default=8000,
            min_value=1200,
            max_value=20000,
        )
        max_continuations = _clamp_int(
            os.getenv("STUDY_MATERIALS_LATEX_MAX_CONTINUATIONS") or 3,
            default=3,
            min_value=0,
            max_value=8,
        )

        # LaTeX conversion is mostly formatting; use minimal reasoning to reduce latency/cost.
        reasoning_cfg = {"effort": "minimal", "exclude": True}

        async def _convert_markdown_to_body(
            md: str,
            *,
            part_index: int,
            part_total: int,
            progress_start: int,
            progress_end: int,
        ) -> Dict[str, Any]:
            await self._emit_status(f"调用模型生成 LaTeX（{part_index}/{part_total}）…")
            p = dict(prompt)
            p["markdown"] = md
            res = await self._call_llm_response(
                messages=[
                    {"role": "system", "content": _latex_convert_system_prompt()},
                    {"role": "user", "content": json.dumps(p, ensure_ascii=False)},
                ],
                model=model,
                temperature=0.2,
                max_tokens=max_tokens,
                reasoning=reasoning_cfg,
                raise_on_fail=True,
            )

            span = max(0, int(progress_end) - int(progress_start))
            p_after_first = int(progress_start) + int(span * 0.7)
            await self._emit_progress(
                percent=min(int(progress_end), max(int(progress_start), p_after_first)),
                stage=f"转换正文（{part_index}/{part_total}）",
                current=part_index,
                total=part_total,
            )
            raw = _normalize_latex_text(str(res.get("content") or "").strip())
            finish_reason = str(res.get("finish_reason") or "").strip().lower()
            usage = res.get("usage") if isinstance(res.get("usage"), dict) else {}
            if not raw:
                raise RuntimeError("llm_empty_response")

            body = _normalize_latex_text(_extract_latex_body(raw))
            conts = 0
            while (
                conts < max_continuations
                and body
                and (
                    _looks_truncated_latex_chunk(raw, finish_reason, usage, max_tokens=max_tokens)
                    or _looks_incomplete_latex(body)
                )
            ):
                await self._emit_status(
                    f"输出疑似被截断，继续补全（{part_index}/{part_total}，续写 {conts + 1}/{max_continuations}）…"
                )
                tail = body[-2000:]
                cont_prompt = {
                    "topic": topic,
                    "subject": subject,
                    "template": template,
                    "requirements": prompt.get("requirements") or [],
                    "markdown": md,
                    "existing_latex_tail": tail,
                    "instructions": [
                        "The previous output appears truncated. Continue the remaining body strictly from the end of existing_latex_tail.",
                        "Output only the LaTeX body that must be appended to <BODY>. Do not repeat previous content and do not output documentclass, preamble, \\begin{document}, \\end{document}, \\maketitle, BEGIN_BODY, or END_BODY.",
                        "If the last line, formula, or environment in existing_latex_tail is unfinished, close it first and then continue.",
                        "Do not output references, external links, or URL lists.",
                    ],
                }
                cont_res = await self._call_llm_response(
                    messages=[
                        {
                            "role": "system",
                            "content": _latex_convert_continuation_system_prompt(),
                        },
                        {"role": "user", "content": json.dumps(cont_prompt, ensure_ascii=False)},
                        {"role": "assistant", "content": tail},
                        {"role": "user", "content": "Continue. Output only the body LaTeX that must be appended, and do not repeat existing_latex_tail."},
                    ],
                    model=model,
                    temperature=0.2,
                    max_tokens=max_tokens,
                    reasoning=reasoning_cfg,
                    raise_on_fail=True,
                )
                addition_raw = _normalize_latex_text(str(cont_res.get("content") or "").strip())
                finish_reason = str(cont_res.get("finish_reason") or "").strip().lower()
                usage = cont_res.get("usage") if isinstance(cont_res.get("usage"), dict) else {}
                if not addition_raw:
                    break
                addition = _normalize_latex_text(_extract_latex_body(addition_raw))
                if not addition:
                    break
                addition = _trim_overlap(body, addition)
                if not addition.strip():
                    break
                if not body.endswith("\n"):
                    body = body + "\n"
                body = (body + addition).rstrip()
                raw = addition_raw
                conts += 1

                if span > 0 and max_continuations > 0:
                    p_now = int(progress_start) + int(span * (0.7 + 0.3 * (conts / max_continuations)))
                    await self._emit_progress(
                        percent=min(int(progress_end), max(int(progress_start), p_now)),
                        stage=f"转换正文（{part_index}/{part_total}）",
                        current=part_index,
                        total=part_total,
                    )
            body = _auto_fix_latex(body).strip()
            looks_truncated = False
            try:
                looks_truncated = bool(
                    body
                    and (
                        _looks_truncated_latex_chunk(raw, finish_reason, usage, max_tokens=max_tokens)
                        or _looks_incomplete_latex(body)
                    )
                )
            except (re.error, TypeError, ValueError):
                looks_truncated = False

            warning = ""
            if looks_truncated:
                warning = f"part {part_index}/{part_total}: output may be truncated; returning partial LaTeX."
                await self._emit_status(f"Warning: {warning}")

            return {
                "body": body,
                "continuations": conts,
                "looks_truncated": looks_truncated,
                "warning": warning,
            }

        conts_total = 0
        kp_header_re = re.compile(r"(?m)^##\s+(?:\d+|[一二三四五六七八九十]+)、\s*.+$")
        matches = list(kp_header_re.finditer(markdown))

        parts: List[str] = []
        if len(matches) <= 1:
            parts = [markdown]
        else:
            pre = markdown[: matches[0].start()].strip()
            if pre:
                parts.append(pre)
            for j, m in enumerate(matches):
                start = m.start()
                end = matches[j + 1].start() if (j + 1) < len(matches) else len(markdown)
                part = markdown[start:end].strip()
                if part:
                    parts.append(part)

        total_parts = max(1, len(parts))
        if total_parts > 1:
            await self._emit_status(f"检测到 {total_parts} 段内容，将分段转换以避免截断…")
        await self._emit_progress(percent=10, stage="准备转换", current=0, total=total_parts)

        bodies: List[str] = []
        parts_meta: List[Dict[str, Any]] = []
        warnings: List[str] = []
        partial = False
        part_concurrency = _clamp_int(
            os.getenv("STUDY_MATERIALS_LATEX_PART_CONCURRENCY") or 2,
            default=2,
            min_value=1,
            max_value=6,
        )
        part_concurrency = min(part_concurrency, total_parts)

        if part_concurrency <= 1 or total_parts <= 1:
            for idx, part in enumerate(parts, start=1):
                p_start = int(10 + (80 * (idx - 1) / total_parts))
                p_end = int(10 + (80 * idx / total_parts))
                await self._emit_progress(
                    percent=p_start,
                    stage=f"转换正文（{idx}/{total_parts}）",
                    current=idx,
                    total=total_parts,
                )
                chunk_res = await _convert_markdown_to_body(
                    part,
                    part_index=idx,
                    part_total=total_parts,
                    progress_start=p_start,
                    progress_end=p_end,
                )
                b = str(chunk_res.get("body") or "").strip()
                if b:
                    bodies.append(b)
                try:
                    conts = int(chunk_res.get("continuations") or 0)
                except (TypeError, ValueError):
                    conts = 0
                conts = max(0, conts)
                conts_total += conts
                looks_truncated = bool(chunk_res.get("looks_truncated"))
                if looks_truncated:
                    partial = True
                warn = str(chunk_res.get("warning") or "").strip()
                if warn:
                    warnings.append(warn)
                parts_meta.append({"part": idx, "continuations": conts, "looks_truncated": looks_truncated})
                await self._emit_progress(
                    percent=p_end,
                    stage=f"转换正文（{idx}/{total_parts}）",
                    current=idx,
                    total=total_parts,
                )
        else:
            await self._emit_status(f"将并行转换正文（并发={part_concurrency}）以减少等待…")
            sem = asyncio.Semaphore(part_concurrency)

            async def _run_part(idx: int, part: str) -> Dict[str, Any]:
                async with sem:
                    p_start = int(10 + (80 * (idx - 1) / total_parts))
                    p_end = int(10 + (80 * idx / total_parts))
                    await self._emit_progress(
                        percent=p_start,
                        stage=f"转换正文（{idx}/{total_parts}）",
                        current=idx,
                        total=total_parts,
                    )
                    res = await _convert_markdown_to_body(
                        part,
                        part_index=idx,
                        part_total=total_parts,
                        progress_start=p_start,
                        progress_end=p_end,
                    )
                    await self._emit_progress(
                        percent=p_end,
                        stage=f"转换正文（{idx}/{total_parts}）",
                        current=idx,
                        total=total_parts,
                    )
                    out = dict(res) if isinstance(res, dict) else {}
                    out["__part_index"] = idx
                    return out

            tasks = [asyncio.create_task(_run_part(i, p)) for i, p in enumerate(parts, start=1)]
            try:
                part_results = await asyncio.gather(*tasks)
            except Exception:
                for t in tasks:
                    if not t.done():
                        t.cancel()
                raise
            part_results.sort(key=lambda x: int(x.get("__part_index") or 0))

            for chunk_res in part_results:
                b = str(chunk_res.get("body") or "").strip()
                if b:
                    bodies.append(b)
                try:
                    conts = int(chunk_res.get("continuations") or 0)
                except (TypeError, ValueError):
                    conts = 0
                conts = max(0, conts)
                conts_total += conts
                looks_truncated = bool(chunk_res.get("looks_truncated"))
                if looks_truncated:
                    partial = True
                warn = str(chunk_res.get("warning") or "").strip()
                if warn:
                    warnings.append(warn)
                try:
                    part_idx = int(chunk_res.get("__part_index") or 0)
                except (TypeError, ValueError):
                    part_idx = 0
                if part_idx <= 0:
                    part_idx = len(parts_meta) + 1
                parts_meta.append({"part": part_idx, "continuations": conts, "looks_truncated": looks_truncated})

        body = "\n\n".join([b for b in bodies if b.strip()]).strip()

        await self._emit_progress(percent=92, stage="整理 LaTeX")
        body = _auto_fix_latex(body).strip()
        tex = _auto_fix_latex(template.replace("<BODY>", body).strip()) + "\n"

        await self._emit_progress(percent=96, stage="写入文件")
        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await publish_generated_text(
            tex,
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
            ctx.working_memory["latex_tex"] = tex
            ctx.working_memory["tex_url"] = url
            ctx.working_memory["tex_filename"] = filename
        except (AttributeError, TypeError):
            logger.debug("latex_export_set_working_memory_failed", exc_info=True)

        await self._emit_progress(percent=100, stage="完成")

        return {
            "tex_url": url,
            "filename": filename,
            "sha256": sha,
            "bytes": size,
            "model": model,
            "continuations": conts_total,
            "partial": bool(partial),
            "warnings": warnings[:10],
            "parts": parts_meta,
            "total_parts": total_parts,
        }
