from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from backend.media.generated import default_generated_media_ttl_s, publish_generated_bytes, publish_generated_text


def render_paper_markdown(
    paper: dict,
    *,
    include_stem: bool = False,
    include_answer: bool = False,
    include_analysis: bool = False,
) -> str:
    name = str(paper.get("paper_name") or paper.get("name") or "试卷").strip()
    pid = paper.get("paper_id") or paper.get("id") or ""
    created = str(paper.get("created_at") or paper.get("createdAt") or "").strip()
    questions = paper.get("questions") if isinstance(paper.get("questions"), list) else []

    lines = [f"# {name}", ""]
    meta = []
    if pid:
        meta.append(f"> 试卷 ID：{pid}")
    if created:
        meta.append(f"> 创建时间：{created}")
    if meta:
        lines.extend(meta)
        lines.append("")

    lines.append("| 题号 | 题型 | 难度 | 知识点 | 题目ID | 来源 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for q in questions:
        if not isinstance(q, dict):
            continue
        order = q.get("order") or q.get("question_order") or ""
        qtype = str(q.get("type") or q.get("question_type") or "").strip()
        diff = str(q.get("difficulty") or "").strip()
        kp = str(q.get("knowledge_point") or q.get("knowledgePoint") or "").strip()
        qid = str(q.get("question_id") or q.get("questionId") or "").strip()
        src = str(q.get("source_url") or q.get("sourceUrl") or "").strip()
        lines.append(f"| {order} | {qtype} | {diff} | {kp} | {qid} | {src} |")

    if include_stem or include_answer or include_analysis:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## 题目内容（本地快照）")
        lines.append("")

        for q in questions:
            if not isinstance(q, dict):
                continue
            qid = str(q.get("question_id") or q.get("questionId") or "").strip()
            order = q.get("order") or q.get("question_order") or ""
            lines.append(f"### {order}. {qid}")
            lines.append("")

            if include_stem:
                stem = str(q.get("stem") or "").strip()
                if stem:
                    lines.append("**题干：**")
                    lines.append("")
                    lines.append(stem)
                    lines.append("")

            if include_answer:
                ans = str(q.get("answer") or "").strip()
                if ans:
                    lines.append("**答案：**")
                    lines.append("")
                    lines.append(ans)
                    lines.append("")

            if include_analysis:
                ana = str(q.get("analysis") or "").strip()
                if ana:
                    lines.append("**解析：**")
                    lines.append("")
                    lines.append(ana)
                    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_paper_latex(
    paper: dict,
    *,
    include_stem: bool = False,
    include_answer: bool = False,
    include_analysis: bool = False,
) -> str:
    name = str(paper.get("paper_name") or paper.get("name") or "试卷").strip()
    questions = paper.get("questions") if isinstance(paper.get("questions"), list) else []

    def _tex_escape(text: str) -> str:
        t = str(text or "")
        repl = {
            "\\": r"\textbackslash{}",
            "&": r"\&",
            "%": r"\%",
            "$": r"\$",
            "#": r"\#",
            "_": r"\_",
            "{": r"\{",
            "}": r"\}",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
        }
        for k, v in repl.items():
            t = t.replace(k, v)
        return t

    lines = [
        r"\documentclass[UTF8,a4paper]{ctexart}",
        r"\usepackage{geometry}",
        r"\usepackage{longtable}",
        r"\usepackage{hyperref}",
        r"\geometry{margin=2cm}",
        r"\begin{document}",
        rf"\section*{{{_tex_escape(name)}}}",
        "",
        r"\begin{longtable}{p{1.2cm}p{2.2cm}p{1.5cm}p{4.0cm}p{3.5cm}p{3.8cm}}",
        r"\hline",
        r"题号 & 题型 & 难度 & 知识点 & 题目ID & 来源 \\",
        r"\hline",
        r"\endhead",
    ]

    for q in questions:
        if not isinstance(q, dict):
            continue
        order = q.get("order") or q.get("question_order") or ""
        qtype = _tex_escape(str(q.get("type") or q.get("question_type") or "").strip())
        diff = _tex_escape(str(q.get("difficulty") or "").strip())
        kp = _tex_escape(str(q.get("knowledge_point") or q.get("knowledgePoint") or "").strip())
        qid = _tex_escape(str(q.get("question_id") or q.get("questionId") or "").strip())
        src = _tex_escape(str(q.get("source_url") or q.get("sourceUrl") or "").strip())
        lines.append(f"{order} & {qtype} & {diff} & {kp} & {qid} & {src} \\\\")

    lines.extend([r"\hline", r"\end{longtable}", ""])

    if include_stem or include_answer or include_analysis:
        lines.append(r"\newpage")
        lines.append(r"\section*{题目内容（本地快照）}")
        lines.append("")
        for q in questions:
            if not isinstance(q, dict):
                continue
            qid = _tex_escape(str(q.get("question_id") or q.get("questionId") or "").strip())
            order = q.get("order") or q.get("question_order") or ""
            lines.append(rf"\subsection*{{{order}. {qid}}}")
            lines.append("")
            if include_stem:
                stem = str(q.get("stem") or "").strip()
                if stem:
                    lines.append(r"\textbf{题干：}\\")
                    lines.append(_tex_escape(stem).replace("\n", r"\\"))
                    lines.append("")
            if include_answer:
                ans = str(q.get("answer") or "").strip()
                if ans:
                    lines.append(r"\textbf{答案：}\\")
                    lines.append(_tex_escape(ans).replace("\n", r"\\"))
                    lines.append("")
            if include_analysis:
                ana = str(q.get("analysis") or "").strip()
                if ana:
                    lines.append(r"\textbf{解析：}\\")
                    lines.append(_tex_escape(ana).replace("\n", r"\\"))
                    lines.append("")

    lines.append(r"\end{document}")
    return "\n".join(lines).rstrip() + "\n"


def _find_latex_engine() -> Optional[str]:
    configured = str(os.getenv("PAPER_EXPORT_LATEX_ENGINE") or os.getenv("LATEX_ENGINE") or "").strip()
    if configured:
        return shutil.which(configured) or configured
    return shutil.which("xelatex") or shutil.which("pdflatex")


def compile_latex_to_pdf(*, tex: str) -> Tuple[Optional[bytes], str]:
    """Compile LaTeX to PDF and return (pdf_bytes, log_text)."""

    engine = _find_latex_engine()
    if not engine:
        return None, "latex_engine_not_found"

    with tempfile.TemporaryDirectory(prefix="paper_export_") as tmp:
        tmp_dir = Path(tmp)
        tex_path = tmp_dir / "paper.tex"
        tex_path.write_text(tex, encoding="utf-8")

        cmd = [
            engine,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            str(tex_path),
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(tmp_dir),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except Exception as exc:
            return None, f"latex_compile_failed: {exc}"

        log_text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        pdf_path = tmp_dir / "paper.pdf"
        if proc.returncode != 0 or not pdf_path.exists():
            return None, log_text[-8000:]

        return pdf_path.read_bytes(), log_text[-8000:]


async def export_paper(
    paper: dict,
    *,
    user_id: str,
    fmt: str,
    include_stem: bool = False,
    include_answer: bool = False,
    include_analysis: bool = False,
) -> Dict[str, Any]:
    """Export paper into `.local/media/generated` and return URLs."""

    fmt_norm = (fmt or "").strip().lower()
    if fmt_norm in {"md", "markdown"}:
        md = render_paper_markdown(
            paper,
            include_stem=include_stem,
            include_answer=include_answer,
            include_analysis=include_analysis,
        )
        out = await publish_generated_text(
            md,
            user_id=user_id,
            ext=".md",
            file_type="md",
            mime_type="text/markdown; charset=utf-8",
            ttl_s=default_generated_media_ttl_s(),
        )
        return {"format": "markdown", **out}

    if fmt_norm in {"tex", "latex"}:
        tex = render_paper_latex(
            paper,
            include_stem=include_stem,
            include_answer=include_answer,
            include_analysis=include_analysis,
        )
        out = await publish_generated_text(
            tex,
            user_id=user_id,
            ext=".tex",
            file_type="tex",
            mime_type="application/x-tex; charset=utf-8",
            ttl_s=default_generated_media_ttl_s(),
        )
        return {"format": "latex", **out}

    if fmt_norm == "pdf":
        tex = render_paper_latex(
            paper,
            include_stem=include_stem,
            include_answer=include_answer,
            include_analysis=include_analysis,
        )
        tex_out = await publish_generated_text(
            tex,
            user_id=user_id,
            ext=".tex",
            file_type="tex",
            mime_type="application/x-tex; charset=utf-8",
            ttl_s=default_generated_media_ttl_s(),
        )
        pdf_bytes, log_text = compile_latex_to_pdf(tex=tex)
        if not pdf_bytes:
            return {
                "format": "pdf",
                "success": False,
                "error": "pdf_compile_failed",
                "log": log_text,
                "tex_url": tex_out["url"],
                "tex_filename": tex_out["filename"],
            }
        pdf_out = await publish_generated_bytes(
            pdf_bytes,
            user_id=user_id,
            ext=".pdf",
            file_type="pdf",
            mime_type="application/pdf",
            ttl_s=default_generated_media_ttl_s(),
        )
        return {
            "format": "pdf",
            "success": True,
            "pdf_url": pdf_out["url"],
            "pdf_filename": pdf_out["filename"],
            "tex_url": tex_out["url"],
            "tex_filename": tex_out["filename"],
        }

    raise ValueError("unsupported_format")
