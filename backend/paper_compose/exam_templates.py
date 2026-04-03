from __future__ import annotations

from typing import Iterable, List, Optional


def get_exam_preamble(*, margin_cm: float = 2.0) -> str:
    """Return a standard, self-contained LaTeX preamble for exam papers."""

    margin_cm = float(margin_cm or 2.0)
    margin_cm = max(1.0, min(margin_cm, 3.5))

    lines: List[str] = [
        r"\documentclass[UTF8,a4paper]{ctexart}",
        r"\usepackage{amsmath}",
        r"\usepackage{amssymb}",
        r"\usepackage{geometry}",
        r"\usepackage{graphicx}",
        r"\usepackage{enumitem}",
        r"\usepackage{fancyhdr}",
        r"\usepackage{hyperref}",
        rf"\geometry{{margin={margin_cm:.2f}cm}}",
        r"\setlength{\parindent}{0pt}",
        r"\setlist[itemize]{leftmargin=*, itemsep=0.3em}",
        r"\setlist[enumerate]{leftmargin=*, itemsep=0.9em}",
        r"\pagestyle{fancy}",
        r"\fancyhf{}",
        r"\cfoot{\thepage}",
    ]
    return "\n".join(lines).rstrip() + "\n"


def format_exam_header(
    *,
    title: str,
    subject: str = "",
    time_limit: str = "",
    total_points: str = "",
    notes: Optional[Iterable[str]] = None,
) -> str:
    """Format the exam header block (expects already-escaped TeX strings)."""

    t = str(title or "").strip() or "试卷"
    subj = str(subject or "").strip()
    time_text = str(time_limit or "").strip()
    points_text = str(total_points or "").strip()

    meta_parts: List[str] = []
    if subj:
        meta_parts.append(f"学科：{subj}")
    if time_text:
        meta_parts.append(f"考试时间：{time_text}")
    if points_text:
        meta_parts.append(f"满分：{points_text}")

    meta_line = "　".join([p for p in meta_parts if p])
    lines: List[str] = [
        r"\begin{center}",
        rf"{{\LARGE \textbf{{{t}}}}}\\[0.4em]",
    ]
    if meta_line:
        lines.append(rf"{{\normalsize {meta_line}}}\\[0.6em]")

    note_lines = [str(x).strip() for x in (notes or []) if str(x or "").strip()]
    if note_lines:
        lines.append(r"\begin{minipage}{0.94\linewidth}")
        lines.append(r"\textbf{注意事项：}")
        lines.append(r"\begin{itemize}")
        for n in note_lines[:10]:
            lines.append(rf"\item {n}")
        lines.append(r"\end{itemize}")
        lines.append(r"\end{minipage}\\[0.4em]")

    lines.append(r"\end{center}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_answer_key_section(*, answers: List[dict]) -> str:
    """Format an answer key section.

    Expected answer dict keys:
    - number: int
    - answer_tex: str
    - analysis_tex: str (optional)
    """

    items = [a for a in (answers or []) if isinstance(a, dict)]
    if not items:
        return ""

    lines: List[str] = [r"\newpage", r"\section*{参考答案}", ""]
    for it in items:
        try:
            num = int(it.get("number") or 0)
        except Exception:
            num = 0
        ans = str(it.get("answer_tex") or "").strip()
        ana = str(it.get("analysis_tex") or "").strip()
        if num <= 0 or (not ans and not ana):
            continue
        lines.append(rf"\textbf{{{num}.}} {ans}\\")
        if ana:
            lines.append(ana)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"

