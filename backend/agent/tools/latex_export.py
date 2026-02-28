from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

from backend.agent.tools.text_utils import _trim_overlap
from backend.agent.types import CompressedContext
from backend.core.settings import LESSON_PLAN_API_KEY, MOONSHOT_API_KEY


def _clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(min_value, min(max_value, n))


_BEGIN_BODY_RE = re.compile(r"%\s*---\s*BEGIN_BODY\s*---", re.IGNORECASE)
_END_BODY_RE = re.compile(r"%\s*---\s*END_BODY\s*---", re.IGNORECASE)
_BEGIN_BODY_LINE_RE = re.compile(r"(?im)^\s*%\s*---\s*BEGIN_BODY\s*---\s*$")
_END_BODY_LINE_RE = re.compile(r"(?im)^\s*%\s*---\s*END_BODY\s*---\s*$")
_LATEX_BEGIN_DOC = "\\begin{document}"
_LATEX_END_DOC = "\\end{document}"


def _strip_verbatim_like_blocks(text: str) -> str:
    s = text or ""
    try:
        s = re.sub(r"(?s)\\begin\{verbatim\}.*?\\end\{verbatim\}", "", s)
        s = re.sub(r"(?s)\\begin\{lstlisting\}.*?\\end\{lstlisting\}", "", s)
        s = re.sub(r"(?s)\\begin\{minted\}.*?\\end\{minted\}", "", s)
    except Exception:
        return text or ""
    return s


def _brace_balance(text: str) -> int:
    bal = 0
    s = text or ""
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n and s[i + 1] in "{}":
            i += 2
            continue
        if ch == "{":
            bal += 1
        elif ch == "}":
            bal -= 1
        if bal < 0:
            return bal
        i += 1
    return bal


def _strip_code_fences(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        first_newline = raw.find("\n")
        if first_newline != -1:
            raw = raw[first_newline + 1 :]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    return raw


def _clean_latex_body(body: str) -> str:
    text = (body or "").strip()
    if not text:
        return ""
    text = _BEGIN_BODY_LINE_RE.sub("", text)
    text = _END_BODY_LINE_RE.sub("", text)
    text = re.sub(r"(?im)^\s*\\maketitle\s*$", "", text)
    text = re.sub(r"(?im)^\s*\\documentclass\b.*$", "", text)
    text = re.sub(r"(?im)^\s*\\begin\{document\}\s*$", "", text)
    text = re.sub(r"(?im)^\s*\\end\{document\}\s*$", "", text)
    text = text.strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_latex_body(text: str) -> str:
    raw = _strip_code_fences(text)
    if not raw:
        return ""
    begin_matches = list(_BEGIN_BODY_RE.finditer(raw))
    if begin_matches:
        begin = begin_matches[-1]
        end = _END_BODY_RE.search(raw, pos=begin.end())
        if end:
            return _clean_latex_body(raw[begin.end() : end.start()])
        return _clean_latex_body(raw[begin.end() :])
    if _LATEX_BEGIN_DOC in raw:
        body = raw.split(_LATEX_BEGIN_DOC, 1)[1]
        if _LATEX_END_DOC in body:
            body = body.split(_LATEX_END_DOC, 1)[0]
        return _clean_latex_body(body)
    return _clean_latex_body(raw)


def _looks_truncated_latex_chunk(text: str, finish_reason: str, usage: Any, *, max_tokens: int) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if (finish_reason or "").strip().lower() == "length":
        return True
    if isinstance(usage, dict):
        try:
            ct = int(usage.get("completion_tokens") or 0)
        except Exception:
            ct = 0
        if ct and max_tokens and ct >= int(max_tokens * 0.95):
            return True
    if _LATEX_BEGIN_DOC in raw and _LATEX_END_DOC not in raw:
        return True
    if _BEGIN_BODY_RE.search(raw) and not _END_BODY_RE.search(raw):
        return True
    try:
        begins = len(re.findall(r"\\begin\{[^}]+\}", raw))
        ends = len(re.findall(r"\\end\{[^}]+\}", raw))
        if begins > ends:
            return True
    except Exception:
        pass
    raw_no_esc = re.sub(r"\\\$", "", raw)
    if raw_no_esc.count("$$") % 2 == 1:
        return True
    if raw_no_esc.replace("$$", "").count("$") % 2 == 1:
        return True
    try:
        raw_sans_verbatim = _strip_verbatim_like_blocks(raw)
        if _brace_balance(raw_sans_verbatim) != 0:
            return True
    except Exception:
        pass
    tail = raw.rstrip()
    if tail and tail[-1] in {"\\", "{", "[", "(", "=", "+", "-", "$"}:
        return True
    return False


def _normalize_latex_text(text: str) -> str:
    s = text or ""
    if not s:
        return ""
    if s.count("\\n") >= 20 and s.count("\n") <= 3:
        s = s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    try:
        s = re.sub(r"\\\\(begin|end)\{", r"\\\1{", s)
        s = re.sub(r"\\\\(item)\b", r"\\\1", s)
        s = re.sub(r"\\\\(section|subsection|subsubsection|paragraph)\b", r"\\\1", s)
        s = re.sub(r"\\\\(includegraphics)\b", r"\\\1", s)
        s = re.sub(r"\\\\(textbf|textit|emph|mathrm|mathbf|mathit|mathcal)\b", r"\\\1", s)
    except Exception:
        return text or ""
    return s


def _looks_incomplete_latex(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if _LATEX_BEGIN_DOC in raw and _LATEX_END_DOC not in raw:
        return True
    if _BEGIN_BODY_RE.search(raw) and not _END_BODY_RE.search(raw):
        return True
    try:
        begins = len(re.findall(r"\\begin\{[^}]+\}", raw))
        ends = len(re.findall(r"\\end\{[^}]+\}", raw))
        if begins > ends:
            return True
    except Exception:
        pass
    raw_no_esc = re.sub(r"\\\$", "", raw)
    if raw_no_esc.count("$$") % 2 == 1:
        return True
    if raw_no_esc.replace("$$", "").count("$") % 2 == 1:
        return True
    try:
        raw_sans_verbatim = _strip_verbatim_like_blocks(raw)
        if _brace_balance(raw_sans_verbatim) != 0:
            return True
    except Exception:
        pass
    tail = raw.rstrip()
    if tail and tail[-1] in {"\\", "{", "[", "(", "=", "+", "-", "$"}:
        return True
    return False


def _auto_fix_latex(text: str) -> str:
    s = _normalize_latex_text(text)
    if not s.strip():
        return ""

    suffix = ""
    if _LATEX_END_DOC in s:
        pre, post = s.split(_LATEX_END_DOC, 1)
        s = pre
        suffix = _LATEX_END_DOC + post

    s_no_verbatim = ""
    try:
        s_no_verbatim = _strip_verbatim_like_blocks(s)
    except Exception:
        s_no_verbatim = s

    try:
        bal = _brace_balance(s_no_verbatim)
    except Exception:
        bal = 0
    if bal > 0:
        s = s + ("}" * min(bal, 24))

    try:
        begins = list(re.finditer(r"\\begin\{([^}]+)\}", s))
        ends = list(re.finditer(r"\\end\{([^}]+)\}", s))
        if len(begins) > len(ends):
            stack: List[str] = []
            for m in re.finditer(r"\\(begin|end)\{([^}]+)\}", s):
                kind = m.group(1)
                name = m.group(2)
                if kind == "begin":
                    stack.append(name)
                else:
                    if stack and stack[-1] == name:
                        stack.pop()
                    elif name in stack:
                        while stack and stack[-1] != name:
                            stack.pop()
                        if stack and stack[-1] == name:
                            stack.pop()
            if stack:
                for name in reversed(stack[-24:]):
                    s = s.rstrip() + "\n\\end{" + name + "}"
    except Exception:
        pass

    try:
        raw_no_esc = re.sub(r"\\\$", "", s)
        if raw_no_esc.count("$$") % 2 == 1:
            s = s.rstrip() + "\n$$\n"
        if raw_no_esc.replace("$$", "").count("$") % 2 == 1:
            s = s.rstrip() + "$"
    except Exception:
        pass

    if suffix:
        if not s.endswith("\n"):
            s += "\n"
        s = s + suffix.lstrip("\n")
    return s


class LatexToolsMixin:
    async def _tool_convert_markdown_to_latex(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """用 LLM 把 Markdown 转成 ElegantBook LaTeX，并发布为可下载 .tex。"""

        topic = str(args.get("topic") or ctx.current_task).strip() or "study_archive"
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)
        # LaTeX export is 100% LLM-dependent; fail fast even if other tools allow fallbacks.
        if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
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
            or os.getenv("STUDY_MATERIALS_WRITER_MODEL")
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
                "请把下面 Markdown 转为 LaTeX，使用 ElegantBook 模板。",
                "只输出 LaTeX 源码，不要 Markdown 代码块，不要额外解释。",
                "请只输出用于替换 <BODY> 的正文 LaTeX（不要输出 documentclass/preamble/\\begin{document}/\\end{document}/\\maketitle，也不要输出 % --- BEGIN_BODY --- 或 % --- END_BODY ---）。",
                "正文用 LaTeX 结构：标题层级 #/##/###/#### 映射为 \\section/\\subsection/\\subsubsection/\\paragraph。",
                "保留数学公式 $...$ 与 $$...$$，确保括号与环境闭合。",
                "列表用 itemize/enumerate；代码块用 verbatim；表格必要时可简化。",
                "图片：只处理 PNG/JPG/JPEG/WebP/GIF/BMP。将 `![](/api/media/generated/xxx.png)` 转为 `\\\\includegraphics[width=0.9\\\\linewidth]{xxx.png}`；遇到 SVG 图片不要插图，改为一句话：`（图略：SVG 见 Markdown 版）`。",
                "不要输出“参考文献/外部链接/URL 列表”。",
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
                    {"role": "system", "content": "你是严谨的 LaTeX 排版助手，输出必须是可编译的 LaTeX。"},
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
            while conts < max_continuations and body and (
                _looks_truncated_latex_chunk(raw, finish_reason, usage, max_tokens=max_tokens)
                or _looks_incomplete_latex(body)
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
                        "上一轮输出疑似被截断。请严格从 existing_latex_tail 的末尾继续补全剩余正文。",
                        "仅输出需要追加到 <BODY> 的 LaTeX 正文，不要重复前文，不要输出 documentclass/preamble/\\begin{document}/\\end{document}/\\maketitle/BEGIN_BODY/END_BODY。",
                        "若 existing_latex_tail 的最后一行/公式/环境未结束，请先补齐闭合再继续。",
                        "不要输出参考文献/外部链接/URL 列表。",
                    ],
                }
                cont_res = await self._call_llm_response(
                    messages=[
                        {
                            "role": "system",
                            "content": "你是严谨的 LaTeX 续写助手，只输出需要追加的正文 LaTeX，不要重复前文。",
                        },
                        {"role": "user", "content": json.dumps(cont_prompt, ensure_ascii=False)},
                        {"role": "assistant", "content": tail},
                        {"role": "user", "content": "继续。只输出需要追加的正文 LaTeX，不要重复 existing_latex_tail。"},
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
            except Exception:
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
                except Exception:
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
                except Exception:
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
                except Exception:
                    part_idx = 0
                if part_idx <= 0:
                    part_idx = len(parts_meta) + 1
                parts_meta.append({"part": part_idx, "continuations": conts, "looks_truncated": looks_truncated})

        body = "\n\n".join([b for b in bodies if b.strip()]).strip()

        await self._emit_progress(percent=92, stage="整理 LaTeX")
        body = _auto_fix_latex(body).strip()
        tex = _auto_fix_latex(template.replace("<BODY>", body).strip()) + "\n"

        await self._emit_progress(percent=96, stage="写入文件")
        tex_bytes = tex.encode("utf-8")
        sha = hashlib.sha256(tex_bytes).hexdigest()
        filename = f"{sha}.tex"
        url = f"/api/media/generated/{filename}"

        repo_root = Path(__file__).resolve().parents[3]
        out_dir = (repo_root / ".local" / "media" / "generated").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        if not out_path.exists():
            out_path.write_bytes(tex_bytes)

        try:
            ctx.working_memory["latex_tex"] = tex
            ctx.working_memory["tex_url"] = url
            ctx.working_memory["tex_filename"] = filename
        except Exception:
            pass

        await self._emit_progress(percent=100, stage="完成")

        return {
            "tex_url": url,
            "filename": filename,
            "sha256": sha,
            "bytes": len(tex_bytes),
            "model": model,
            "continuations": conts_total,
            "partial": bool(partial),
            "warnings": warnings[:10],
            "parts": parts_meta,
            "total_parts": total_parts,
        }

    async def _tool_refine_latex(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """对 LaTeX 做二次修订，尽量减少编译失败与排版问题。"""

        topic = str(args.get("topic") or ctx.current_task).strip() or "study_archive"
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)
        # LaTeX refining is LLM-dependent; fail fast to avoid cascading "latex_missing" errors.
        if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
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
            pass

        compile_error = str(args.get("compile_error") or "").strip()
        if len(compile_error) > 1800:
            compile_error = compile_error[:1799].rstrip() + "…"

        always_refine_raw = str(os.getenv("STUDY_MATERIALS_LATEX_ALWAYS_REFINE") or "0").strip().lower()
        always_refine = always_refine_raw in {"1", "true", "yes", "y", "on"}
        if (not compile_error) and (not always_refine):
            tex_bytes = (tex.strip() + "\n").encode("utf-8")
            sha = hashlib.sha256(tex_bytes).hexdigest()
            filename = f"{sha}.tex"
            url = f"/api/media/generated/{filename}"

            repo_root = Path(__file__).resolve().parents[3]
            out_dir = (repo_root / ".local" / "media" / "generated").resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / filename
            if not out_path.exists():
                out_path.write_bytes(tex_bytes)

            try:
                ctx.working_memory["latex_tex"] = tex.strip() + "\n"
                ctx.working_memory["tex_url"] = url
                ctx.working_memory["tex_filename"] = filename
            except Exception:
                pass

            return {"tex_url": url, "filename": filename, "sha256": sha, "bytes": len(tex_bytes), "model": ""}

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
        while conts < max_continuations and refined and (
            _looks_truncated_latex_chunk(refined, finish_reason, usage, max_tokens=refine_max_tokens)
            or _looks_incomplete_latex(refined)
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

        tex_bytes = (refined.strip() + "\n").encode("utf-8")
        import hashlib

        sha = hashlib.sha256(tex_bytes).hexdigest()
        filename = f"{sha}.tex"
        url = f"/api/media/generated/{filename}"

        repo_root = Path(__file__).resolve().parents[3]
        out_dir = (repo_root / ".local" / "media" / "generated").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        if not out_path.exists():
            out_path.write_bytes(tex_bytes)

        try:
            ctx.working_memory["latex_tex"] = refined.strip() + "\n"
            ctx.working_memory["tex_url"] = url
            ctx.working_memory["tex_filename"] = filename
        except Exception:
            pass

        return {"tex_url": url, "filename": filename, "sha256": sha, "bytes": len(tex_bytes), "model": model}

    async def _tool_compile_latex_to_pdf(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """编译 LaTeX 为 PDF，并发布为可下载文件。"""

        topic = str(args.get("topic") or ctx.current_task).strip() or "study_archive"

        tex = args.get("latex")
        if not isinstance(tex, str) or not tex.strip():
            tex = str(ctx.working_memory.get("latex_tex") or "").strip()
        if not tex:
            raise ValueError("latex_missing")

        tex = _auto_fix_latex(tex).strip() + "\n"
        try:
            ctx.working_memory["latex_tex"] = tex
        except Exception:
            pass

        repo_root = Path(__file__).resolve().parents[3]
        gen_dir = (repo_root / ".local" / "media" / "generated").resolve()
        gen_dir.mkdir(parents=True, exist_ok=True)

        build_dir = (repo_root / ".local" / "latex_build" / uuid.uuid4().hex[:12]).resolve()
        build_dir.mkdir(parents=True, exist_ok=True)

        tex_path = build_dir / "main.tex"
        tex_path.write_text(tex, encoding="utf-8")

        # Copy local generated images referenced by includegraphics into build dir.
        try:
            includes = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex)
        except Exception:
            includes = []
        copied = 0
        missing: List[str] = []
        for inc in includes[:80]:
            name = str(inc or "").strip()
            if not name:
                continue
            # Strip any path prefixes and keep basename only.
            base = Path(name).name
            if not base:
                continue
            src = gen_dir / base
            if not src.exists() or not src.is_file():
                # Try to resolve /api/media/generated/<file>
                if base.startswith("generated") and "/" in name:
                    base2 = name.split("/")[-1]
                    src = gen_dir / base2
                if not src.exists() or not src.is_file():
                    missing.append(base)
                    continue
            dst = build_dir / base
            try:
                if not dst.exists():
                    dst.write_bytes(src.read_bytes())
                copied += 1
            except Exception:
                continue

        # Compile with xelatex directly (avoid latexmk dependency on perl on Windows/MiKTeX).
        import subprocess

        cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "main.tex"]
        # First-time MiKTeX compilation may be slow (font cache / on-the-fly package install).
        timeout_s = float(os.getenv("STUDY_MATERIALS_LATEX_TIMEOUT_S") or 600)
        timeout_s = max(30.0, min(timeout_s, 60.0 * 20.0))

        proc = None
        try:
            # Two passes to resolve references/TOC reliably.
            for _ in range(2):
                proc = subprocess.run(
                    cmd,
                    cwd=str(build_dir),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_s,
                )
                if proc.returncode != 0:
                    break
        except FileNotFoundError as exc:
            hint = (
                "xelatex not found. Install a LaTeX engine (MiKTeX or TeX Live) and make sure `xelatex` is on PATH. "
                "Windows example: `winget install MiKTeX.MiKTeX` (or `choco install miktex`)."
            )
            await self._emit_status(f"PDF 编译已跳过：{hint}")
            return {
                "skipped": True,
                "reason": "latex_engine_not_found",
                "hint": hint,
                "engine": "xelatex",
                "error": str(exc),
            }

        if proc is None or proc.returncode != 0:
            stderr = (getattr(proc, "stderr", "") or "").strip()
            stdout = (getattr(proc, "stdout", "") or "").strip()
            msg = stderr[-2000:] if stderr else stdout[-2000:]
            raise RuntimeError(f"latex_compile_failed: {msg}")

        pdf_path = build_dir / "main.pdf"
        if not pdf_path.exists() or not pdf_path.is_file():
            raise RuntimeError("pdf_missing")

        pdf_bytes = pdf_path.read_bytes()

        import hashlib

        sha = hashlib.sha256(pdf_bytes).hexdigest()
        filename = f"{sha}.pdf"
        url = f"/api/media/generated/{filename}"
        out_path = gen_dir / filename
        if not out_path.exists():
            out_path.write_bytes(pdf_bytes)

        try:
            ctx.working_memory["pdf_url"] = url
            ctx.working_memory["pdf_filename"] = filename
        except Exception:
            pass

        return {
            "pdf_url": url,
            "filename": filename,
            "sha256": sha,
            "bytes": len(pdf_bytes),
            "topic": topic,
            "copied_images": copied,
            "missing_images": missing[:20],
            "engine": "xelatex",
        }
