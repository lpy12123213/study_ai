
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from backend.core.logging_utils import get_logger
from backend.paper_compose.exam_templates import format_answer_key_section, format_exam_header, get_exam_preamble
from backend.paper_compose.exporters.tex_escape import _smart_tex_escape

logger = get_logger(__name__)

def render_paper_latex(
    paper: dict,
    *,
    include_stem: bool = False,
    include_answer: bool = False,
    include_analysis: bool = False,
) -> str:
    name = str(paper.get("paper_name") or paper.get("name") or "试卷").strip()
    pid = str(paper.get("paper_id") or paper.get("id") or "").strip()
    created = str(paper.get("created_at") or paper.get("createdAt") or "").strip()
    questions = paper.get("questions") if isinstance(paper.get("questions"), list) else []

    def _generated_filename_from_url(url: str) -> str:
        raw = str(url or "").strip()
        if not raw:
            return ""
        raw = raw.split("?", 1)[0]
        token = "/api/media/generated/"
        if token in raw:
            raw = raw.split(token, 1)[-1]
        raw = raw.strip().strip("/").strip()
        # Only allow basenames to prevent path traversal in the compiler stage.
        raw = raw.replace("\\", "/").split("/")[-1]
        return raw

    # Standard exam layout (header -> grouped questions -> optional answer key).
    notes = [
        "请将所有答案写在答题纸上，写在本试卷上无效。",
        "作答前请仔细审题，注意步骤与表达规范。",
    ]
    if pid:
        notes.append(f"试卷ID：{_smart_tex_escape(pid)}")
    if created:
        notes.append(f"创建时间：{_smart_tex_escape(created)}")

    lines: List[str] = [get_exam_preamble(margin_cm=2.0), r"\begin{document}"]
    lines.append(
        format_exam_header(
            title=_smart_tex_escape(name),
            subject=_smart_tex_escape(str(paper.get("subject") or "").strip()),
            time_limit=_smart_tex_escape(str(paper.get("time_limit") or "").strip()),
            total_points=_smart_tex_escape(str(paper.get("total_points") or "").strip()),
            notes=notes,
        ).rstrip()
    )

    # Group by question type (preserve first-seen ordering).
    groups: List[tuple[str, List[dict]]] = []
    groups_by_name: dict[str, List[dict]] = {}
    for q in questions:
        if not isinstance(q, dict):
            continue
        qtype = str(q.get("type") or q.get("question_type") or "").strip() or "其他题"
        if qtype not in groups_by_name:
            groups_by_name[qtype] = []
            groups.append((qtype, groups_by_name[qtype]))
        groups_by_name[qtype].append(q)

    if not groups:
        lines.append(r"\section*{（无题目）}")
        lines.append(r"\end{document}")
        return "\n".join(lines).rstrip() + "\n"

    qnum = 0
    answers: List[dict] = []

    for group_name, qs in groups:
        lines.append(rf"\section*{{{_smart_tex_escape(group_name)}}}")
        lines.append("")
        for q in qs:
            if not isinstance(q, dict):
                continue
            qnum += 1
            qid = str(q.get("question_id") or q.get("questionId") or "").strip()
            points = q.get("points") if q.get("points") is not None else q.get("score")
            points_text = ""
            try:
                if points is not None and str(points).strip():
                    points_text = f"（{_smart_tex_escape(str(points).strip())}分）"
            except (TypeError, ValueError):
                points_text = ""

            stem = str(q.get("stem") or "").strip()
            if not include_stem and not stem:
                stem_tex = rf"\textit{{题目ID：{_smart_tex_escape(qid) or 'unknown'}}}"
            elif include_stem:
                stem_tex = _smart_tex_escape(stem).replace("\n", r"\\")
            else:
                # include_stem=false but stem exists: keep it out for safety.
                stem_tex = rf"\textit{{题目ID：{_smart_tex_escape(qid) or 'unknown'}}}"

            lines.append(rf"\textbf{{{qnum}.}} {stem_tex} {points_text}".rstrip())

            # Optional diagrams field: emit local includegraphics (compiler copies assets).
            diagrams = q.get("diagrams")
            if isinstance(diagrams, list) and diagrams:
                for d in diagrams[:3]:
                    if not isinstance(d, dict):
                        continue
                    filename = str(d.get("filename") or "").strip() or _generated_filename_from_url(str(d.get("url") or ""))
                    if not filename:
                        continue
                    lines.append(r"\begin{center}")
                    lines.append(rf"\includegraphics[width=0.72\linewidth]{{{_smart_tex_escape(filename)}}}")
                    cap = str(d.get("caption") or "").strip()
                    if cap:
                        lines.append(rf"\\[0.2em]{{\small {_smart_tex_escape(cap)}}}")
                    lines.append(r"\end{center}")

            lines.append("")

            if include_answer or include_analysis:
                ans = str(q.get("answer") or "").strip() if include_answer else ""
                ana = str(q.get("analysis") or "").strip() if include_analysis else ""
                answer_tex = _smart_tex_escape(ans).replace("\n", r"\\") if ans else ""
                analysis_tex = _smart_tex_escape(ana).replace("\n", r"\\") if ana else ""
                if answer_tex or analysis_tex:
                    answers.append({"number": qnum, "answer_tex": answer_tex, "analysis_tex": analysis_tex})

    if answers:
        lines.append(format_answer_key_section(answers=answers).rstrip())

    lines.append(r"\end{document}")
    return "\n".join(lines).rstrip() + "\n"


def _find_latex_engine() -> Optional[str]:
    configured = str(os.getenv("PAPER_EXPORT_LATEX_ENGINE") or "").strip()
    if configured:
        return shutil.which(configured) or configured
    return shutil.which("xelatex") or shutil.which("pdflatex")


def _resolve_paper_export_latex_timeout_s(timeout_s: Optional[float]) -> float:
    raw = str(os.getenv("PAPER_EXPORT_LATEX_TIMEOUT_S") or "").strip()
    if timeout_s is None or float(timeout_s or 0) <= 0:
        # Default: keep it short to avoid accidental long hangs in API exports.
        # Users can override via env when they have a full TeX distribution and want longer runs.
        try:
            timeout_s = float(raw) if raw else 30.0
        except (TypeError, ValueError):
            timeout_s = 30.0

    timeout_s = float(timeout_s or 30.0)
    return max(5.0, min(timeout_s, 60.0 * 20.0))


def compile_latex_to_pdf(*, tex: str, timeout_s: Optional[float] = None) -> Tuple[Optional[bytes], str]:
    """Compile LaTeX to PDF and return (pdf_bytes, log_text)."""

    engine = _find_latex_engine()
    if not engine:
        return None, "latex_engine_not_found"

    timeout_s = _resolve_paper_export_latex_timeout_s(timeout_s)

    def _copy_includegraphics_assets(*, tex_text: str, tmp_dir: Path) -> int:
        # Copy referenced images from `.local/media/generated/` into the build dir,
        # so \includegraphics{sha.png} can resolve.
        repo_root = Path(__file__).resolve().parents[3]
        generated_dir = (repo_root / ".local" / "media" / "generated").resolve()
        if not generated_dir.exists():
            return 0

        pattern = re.compile(r"\\includegraphics(?:\\[[^\\]]*\\])?\\{([^\\}]+)\\}")
        copied = 0
        for m in pattern.finditer(tex_text or ""):
            raw = str(m.group(1) or "").strip()
            if not raw:
                continue
            raw = raw.split("?", 1)[0].strip()
            # Only allow basenames to avoid escaping the temp dir.
            filename = raw.replace("\\", "/").split("/")[-1]
            if not filename or any(ch in filename for ch in [":", "\x00"]):
                continue

            # If extension omitted, try common ones.
            candidates = [filename]
            if "." not in filename:
                candidates = [f"{filename}{ext}" for ext in [".png", ".jpg", ".jpeg", ".pdf", ".svg"]]

            for cand in candidates:
                src = (generated_dir / cand).resolve()
                try:
                    src.relative_to(generated_dir)
                except ValueError:
                    continue
                if not src.exists() or not src.is_file():
                    continue
                dst = (tmp_dir / cand).resolve()
                if dst.exists():
                    break
                try:
                    shutil.copyfile(str(src), str(dst))
                    copied += 1
                except OSError:
                    logger.warning(
                        "paper_export_asset_copy_failed",
                        extra={"src": str(src), "dst": str(dst)},
                        exc_info=True,
                    )
                break
        return copied

    with tempfile.TemporaryDirectory(prefix="paper_export_") as tmp:
        tmp_dir = Path(tmp)
        tex_path = tmp_dir / "paper.tex"
        tex_path.write_text(tex, encoding="utf-8")

        _copy_includegraphics_assets(tex_text=tex, tmp_dir=tmp_dir)

        cmd = [
            engine,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            str(tex_path),
        ]
        last_log = ""
        for _ in range(2):
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(tmp_dir),
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return None, "latex_compile_timeout"
            except (OSError, subprocess.SubprocessError) as exc:
                return None, f"latex_compile_failed: {exc}"

            last_log = (proc.stdout or "") + "\n" + (proc.stderr or "")
            if proc.returncode != 0:
                break

        pdf_path = tmp_dir / "paper.pdf"
        if not pdf_path.exists():
            return None, last_log[-8000:]

        return pdf_path.read_bytes(), last_log[-8000:]


async def compile_latex_to_pdf_async(*, tex: str, timeout_s: Optional[float] = None) -> Tuple[Optional[bytes], str]:
    """Async wrapper around the sync compiler to avoid blocking the event loop."""

    timeout_s = _resolve_paper_export_latex_timeout_s(timeout_s)

    try:
        # We still keep a wall-clock timeout guard to prevent thread pool stalls.
        return await asyncio.wait_for(
            asyncio.to_thread(compile_latex_to_pdf, tex=tex, timeout_s=timeout_s),
            timeout=timeout_s + 5.0,
        )
    except asyncio.TimeoutError:
        return None, "latex_compile_timeout"
