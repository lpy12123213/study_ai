from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from backend.core.settings import LESSON_PLAN_MODEL
from backend.lesson_plan_v2.common import GENERATED_DIR, extract_json_obj, lpv2_infinite_max_tokens
from backend.lesson_plan_v2.llm import call_llm_text


def publish_generated_bytes(data: bytes, *, ext: str) -> Dict[str, Any]:
    suffix = (ext or "").strip().lower()
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    sha = hashlib.sha256(data).hexdigest()
    filename = f"{sha}{suffix}"
    url = f"/api/media/generated/{filename}"

    out_path = (GENERATED_DIR / filename).resolve()
    if not out_path.exists():
        out_path.write_bytes(data)

    return {"url": url, "filename": filename, "sha256": sha, "bytes": len(data)}


def publish_generated_text(text: str, *, ext: str) -> Dict[str, Any]:
    t = text or ""
    if not t.endswith("\n"):
        t += "\n"
    return publish_generated_bytes(t.encode("utf-8"), ext=ext)


async def convert_markdown_to_latex(*, markdown: str, title: str, subject: str) -> str:
    model = str(
        os.getenv("LESSON_PLAN_LATEX_MODEL") or os.getenv("STUDY_MATERIALS_LATEX_MODEL") or LESSON_PLAN_MODEL
    ).strip() or LESSON_PLAN_MODEL

    safe_title = (title or "").replace("{", "\\{").replace("}", "\\}").strip() or "教案"
    template = (
        r"\documentclass[lang=cn]{elegantbook}" "\n"
        r"\usepackage{amsmath,amssymb}" "\n"
        r"\usepackage{graphicx}" "\n"
        r"\usepackage{hyperref}" "\n"
        r"\usepackage{booktabs,longtable}" "\n"
        r"\usepackage{xcolor}" "\n"
        r"\hypersetup{colorlinks=true,linkcolor=blue,urlcolor=blue}" "\n"
        r"\title{" + safe_title + r"}" "\n"
        r"\author{}" "\n"
        r"\date{\today}" "\n"
        r"\begin{document}" "\n"
        r"\maketitle" "\n\n"
        r"% --- BEGIN_BODY ---" "\n"
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
    model = str(os.getenv("LESSON_PLAN_LATEX_REFINE_MODEL") or os.getenv("LESSON_PLAN_LATEX_MODEL") or LESSON_PLAN_MODEL).strip() or LESSON_PLAN_MODEL

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


def compile_latex_to_pdf(*, latex: str) -> Dict[str, Any]:
    if shutil.which("xelatex") is None:
        raise RuntimeError("latex_engine_not_found: xelatex")

    build_dir = (GENERATED_DIR / f"tmp_latex_{uuid.uuid4().hex[:10]}").resolve()
    build_dir.mkdir(parents=True, exist_ok=True)

    try:
        tex_path = build_dir / "main.tex"
        tex_path.write_text(latex or "", encoding="utf-8")

        timeout_raw = (os.getenv("LESSON_PLAN_LATEX_TIMEOUT_S") or os.getenv("STUDY_MATERIALS_LATEX_TIMEOUT_S") or "").strip()
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

        return publish_generated_bytes(pdf_path.read_bytes(), ext=".pdf")
    finally:
        try:
            shutil.rmtree(build_dir, ignore_errors=True)
        except Exception:
            pass

