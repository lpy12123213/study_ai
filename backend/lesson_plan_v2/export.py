from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from typing import Any, Dict

from backend.core.logging_utils import get_logger
from backend.core.settings import LESSON_PLAN_MODEL
from backend.lesson_plan_v2.common import GENERATED_DIR, lpv2_infinite_max_tokens
from backend.lesson_plan_v2.llm import call_llm_text
from backend.media.generated import default_generated_media_ttl_s
from backend.media.generated import publish_generated_bytes as _publish_bytes
from backend.media.generated import publish_generated_text as _publish_text

logger = get_logger(__name__)


async def publish_generated_bytes(
    data: bytes, *, user_id: str, ext: str, file_type: str = "", mime_type: str = ""
) -> Dict[str, Any]:
    suffix = (ext or "").strip().lower()
    kind = (file_type or "").strip().lower()
    if not kind:
        if suffix in {".md", "md"}:
            kind = "md"
        elif suffix in {".tex", ".latex", "tex", "latex"}:
            kind = "tex"
        elif suffix in {".pdf", "pdf"}:
            kind = "pdf"
        else:
            kind = "file"
    return await _publish_bytes(
        data,
        user_id=user_id,
        ext=ext,
        file_type=kind,
        mime_type=mime_type,
        ttl_s=default_generated_media_ttl_s(),
    )


async def publish_generated_text(
    text: str, *, user_id: str, ext: str, file_type: str = "", mime_type: str = ""
) -> Dict[str, Any]:
    suffix = (ext or "").strip().lower()
    kind = (file_type or "").strip().lower()
    if not kind:
        if suffix in {".md", "md"}:
            kind = "md"
        elif suffix in {".tex", ".latex", "tex", "latex"}:
            kind = "tex"
        else:
            kind = "text"
    return await _publish_text(
        text,
        user_id=user_id,
        ext=ext,
        file_type=kind,
        mime_type=mime_type,
        ttl_s=default_generated_media_ttl_s(),
    )


async def convert_markdown_to_latex(*, markdown: str, title: str, subject: str) -> str:
    model = (
        str(
            os.getenv("LESSON_PLAN_LATEX_MODEL") or os.getenv("STUDY_MATERIALS_LATEX_MODEL") or LESSON_PLAN_MODEL
        ).strip()
        or LESSON_PLAN_MODEL
    )

    safe_title = (title or "").replace("{", "\\{").replace("}", "\\}").strip() or "教案"
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
        r"\title{" + safe_title + r"}"
        "\n"
        r"\author{}"
        "\n"
        r"\date{\today}"
        "\n"
        r"\begin{document}"
        "\n"
        r"\maketitle"
        "\n\n"
        r"% --- BEGIN_BODY ---"
        "\n"
    )
    tail = "\n% --- END_BODY ---\n\\end{document}\n"

    prompt = {
        "subject": subject,
        "title": title,
        "requirements": [
            "请将下面的 Markdown 教案转换为 LaTeX（中文，适配 elegantbook 文档类）。",
            "只输出 LaTeX 正文（不包含 \\documentclass 等前导，不包含 \\begin{document}/\\end{document}）。",
            "尽量保留标题层级（# -> \\section, ## -> \\subsection, ### -> \\subsubsection）。",
            "表格尽量用 longtable 或 tabular；列表用 itemize/enum。不要输出 Markdown 代码块。",
        ],
        "markdown": markdown,
    }

    body = await call_llm_text(
        messages=[
            {"role": "system", "content": "你是严谨的排版助手。"},
            {"role": "user", "content": str(prompt)},
        ],
        model=model,
        temperature=0.2,
        max_tokens=lpv2_infinite_max_tokens(),
        raise_on_fail=True,
    )

    body_stripped = body.strip()
    if body_stripped.startswith("\\documentclass") or "\\begin{document}" in body_stripped:
        # Best-effort: try to extract document body.
        start = body_stripped.find("\\begin{document}")
        end = body_stripped.rfind("\\end{document}")
        if start >= 0 and end > start:
            body_stripped = body_stripped[start + len("\\begin{document}") : end].strip()

    return template + body_stripped + tail


async def refine_latex(*, latex: str, topic: str, subject: str, compile_error: str = "") -> str:
    model = (
        str(
            os.getenv("LESSON_PLAN_LATEX_REFINE_MODEL") or os.getenv("LESSON_PLAN_LATEX_MODEL") or LESSON_PLAN_MODEL
        ).strip()
        or LESSON_PLAN_MODEL
    )

    prompt = {
        "subject": subject,
        "topic": topic,
        "compile_error": compile_error,
        "requirements": [
            "下面是一份 LaTeX 文档（elegantbook）。如果存在编译错误，请修复；否则做小幅排版改进。",
            "只输出修复后的完整 LaTeX（包含 \\documentclass ... \\end{document}）。",
            "不要输出解释文字，不要输出 Markdown。",
        ],
        "latex": latex,
    }

    out = await call_llm_text(
        messages=[
            {"role": "system", "content": "你是LaTeX修复助手。"},
            {"role": "user", "content": str(prompt)},
        ],
        model=model,
        temperature=0.2,
        max_tokens=lpv2_infinite_max_tokens(),
        raise_on_fail=True,
    )
    cleaned = out.strip()
    return cleaned if cleaned else latex


async def compile_latex_to_pdf(*, latex: str, user_id: str) -> Dict[str, Any]:
    if shutil.which("xelatex") is None:
        raise RuntimeError("latex_engine_not_found: xelatex")

    build_dir = (GENERATED_DIR / f"tmp_latex_{uuid.uuid4().hex[:10]}").resolve()
    build_dir.mkdir(parents=True, exist_ok=True)

    try:
        tex_path = build_dir / "main.tex"
        tex_path.write_text(latex or "", encoding="utf-8")

        timeout_raw = (
            os.getenv("LESSON_PLAN_LATEX_TIMEOUT_S") or os.getenv("STUDY_MATERIALS_LATEX_TIMEOUT_S") or ""
        ).strip()
        try:
            timeout_s = float(timeout_raw) if timeout_raw else 40.0
        except Exception:
            timeout_s = 40.0
        timeout_s = max(10.0, min(timeout_s, 300.0))

        start = time.monotonic()
        cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"]
        proc = subprocess.run(
            cmd,
            cwd=str(build_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            check=False,
        )
        _ = start  # keep for potential future logging

        if proc.returncode != 0:
            stdout = proc.stdout.decode("utf-8", errors="ignore") if proc.stdout else ""
            stderr = proc.stderr.decode("utf-8", errors="ignore") if proc.stderr else ""
            msg = (stderr[-2000:] if stderr else stdout[-2000:]).strip()
            raise RuntimeError(f"latex_compile_failed: {msg}")

        pdf_path = build_dir / "main.pdf"
        if not pdf_path.exists() or not pdf_path.is_file():
            raise RuntimeError("pdf_missing")

        return await publish_generated_bytes(
            pdf_path.read_bytes(), user_id=user_id, ext=".pdf", file_type="pdf", mime_type="application/pdf"
        )
    finally:
        try:
            shutil.rmtree(build_dir, ignore_errors=True)
        except Exception:
            logger.debug("lesson_plan_export_cleanup_failed", extra={"build_dir": str(build_dir)}, exc_info=True)
