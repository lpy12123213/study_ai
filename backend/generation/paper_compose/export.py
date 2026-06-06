
from __future__ import annotations

from typing import Any, Dict

from backend.database.repositories.question.question_cache import get_question_cache
from backend.media.generated import default_generated_media_ttl_s, publish_generated_bytes, publish_generated_text
from backend.generation.paper_compose.exporters.docx import render_paper_docx_bytes
from backend.generation.paper_compose.exporters.latex import (
    compile_latex_to_pdf as compile_latex_to_pdf,
)
from backend.generation.paper_compose.exporters.latex import compile_latex_to_pdf_async, render_paper_latex
from backend.generation.paper_compose.exporters.markdown import render_paper_markdown


def _canonical_export_format(fmt: str) -> str:
    fmt_norm = (fmt or "").strip().lower()
    if fmt_norm in {"md", "markdown"}:
        return "markdown"
    if fmt_norm in {"tex", "latex"}:
        return "latex"
    if fmt_norm in {"pdf", "docx", "word"}:
        return "docx" if fmt_norm == "word" else fmt_norm
    return fmt_norm or "markdown"


def _part_primary_url(part: Dict[str, Any]) -> str:
    return str(part.get("pdf_url") or part.get("url") or part.get("tex_url") or "").strip()


def _part_primary_filename(part: Dict[str, Any]) -> str:
    return str(part.get("pdf_filename") or part.get("filename") or part.get("tex_filename") or "").strip()


def _add_part_aliases(out: Dict[str, Any], *, camel_prefix: str, snake_prefix: str, part: Dict[str, Any]) -> None:
    url = _part_primary_url(part)
    filename = _part_primary_filename(part)
    if url:
        out[f"{camel_prefix}Url"] = url
        out[f"{snake_prefix}_url"] = url
    if filename:
        out[f"{camel_prefix}Filename"] = filename
        out[f"{snake_prefix}_filename"] = filename

    tex_url = str(part.get("tex_url") or "").strip()
    tex_filename = str(part.get("tex_filename") or "").strip()
    if tex_url:
        out[f"{camel_prefix}TexUrl"] = tex_url
        out[f"{snake_prefix}_tex_url"] = tex_url
    if tex_filename:
        out[f"{camel_prefix}TexFilename"] = tex_filename
        out[f"{snake_prefix}_tex_filename"] = tex_filename


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

    hydrated_paper = dict(paper or {})
    questions = hydrated_paper.get("questions") if isinstance(hydrated_paper.get("questions"), list) else []
    if (include_stem or include_answer or include_analysis) and questions:
        qids = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            qid = str(q.get("question_id") or q.get("questionId") or "").strip()
            if qid:
                qids.append(qid)
        cache = await get_question_cache(question_ids=qids)
        for q in questions:
            if not isinstance(q, dict):
                continue
            qid = str(q.get("question_id") or q.get("questionId") or "").strip()
            rec = cache.get(qid) if qid else None
            if not isinstance(rec, dict):
                continue
            if include_stem and not str(q.get("stem") or "").strip():
                q["stem"] = str(rec.get("stem") or "").strip()
            if include_answer and not str(q.get("answer") or "").strip():
                q["answer"] = str(rec.get("answer") or "").strip()
            if include_analysis and not str(q.get("analysis") or "").strip():
                q["analysis"] = str(rec.get("analysis") or "").strip()
            if not str(q.get("source_url") or "").strip():
                q["source_url"] = str(rec.get("source_url") or "").strip()

    fmt_norm = (fmt or "").strip().lower()
    if fmt_norm in {"md", "markdown"}:
        md = render_paper_markdown(
            hydrated_paper,
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
            hydrated_paper,
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
            hydrated_paper,
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
        pdf_bytes, log_text = await compile_latex_to_pdf_async(tex=tex)
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

    if fmt_norm in {"docx", "word"}:
        docx_bytes = render_paper_docx_bytes(
            hydrated_paper,
            include_stem=include_stem,
            include_answer=include_answer,
            include_analysis=include_analysis,
        )
        out = await publish_generated_bytes(
            docx_bytes,
            user_id=user_id,
            ext=".docx",
            file_type="docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ttl_s=default_generated_media_ttl_s(),
        )
        return {"format": "docx", "success": True, **out}

    raise ValueError("unsupported_format")


async def export_paper_bundle(
    paper: dict,
    *,
    user_id: str,
    fmt: str,
    split_bundle: bool = True,
) -> Dict[str, Any]:
    """Export a student exam paper and a separate answer key for the same paper."""

    exam_out = await export_paper(
        paper,
        user_id=user_id,
        fmt=fmt,
        include_stem=True,
        include_answer=False,
        include_analysis=False,
    )
    answer_out = await export_paper(
        paper,
        user_id=user_id,
        fmt=fmt,
        include_stem=True,
        include_answer=True,
        include_analysis=True,
    )

    exam_ok = not (isinstance(exam_out, dict) and exam_out.get("success") is False)
    answer_ok = not (isinstance(answer_out, dict) and answer_out.get("success") is False)
    result: Dict[str, Any] = {
        "format": str(exam_out.get("format") or answer_out.get("format") or _canonical_export_format(fmt)),
        "success": bool(exam_ok and answer_ok),
        "splitBundle": bool(split_bundle),
        "split_bundle": bool(split_bundle),
        "examPaper": dict(exam_out),
        "exam_paper": dict(exam_out),
        "answerKey": dict(answer_out),
        "answer_key": dict(answer_out),
    }
    _add_part_aliases(result, camel_prefix="examPaper", snake_prefix="exam_paper", part=exam_out)
    _add_part_aliases(result, camel_prefix="answerKey", snake_prefix="answer_key", part=answer_out)
    if not result["success"]:
        result["error"] = "split_export_failed"
    return result
