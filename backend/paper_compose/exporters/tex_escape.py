
from __future__ import annotations

import re
from typing import List

_TEX_ESCAPE_REPL = {
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
_TEX_ESCAPE_PATTERN = re.compile(r"[\\&%$#_{}~^]")
_TEX_MATH_SPAN_PATTERN = re.compile(r"(\\\((?:.|\n)*?\\\)|\\\[(?:.|\n)*?\\\])", re.DOTALL)


def _escape_plain_tex(text: str) -> str:
    # IMPORTANT: use a single-pass regexp replacement so the replacement
    # strings (e.g. \textbackslash{}) won't be re-escaped again.
    t = str(text or "")
    return _TEX_ESCAPE_PATTERN.sub(lambda m: _TEX_ESCAPE_REPL.get(m.group(0), m.group(0)), t)


def _smart_tex_escape(text: str) -> str:
    """Escape TeX special chars outside math spans \\(...\\) and \\[...\\]."""

    raw = str(text or "")
    if not raw:
        return ""

    parts = _TEX_MATH_SPAN_PATTERN.split(raw)
    if len(parts) <= 1:
        return _escape_plain_tex(raw)

    out: List[str] = []
    for idx, part in enumerate(parts):
        if not part:
            continue
        if idx % 2 == 1 and (part.startswith("\\(") and part.endswith("\\)")):
            out.append(part)
            continue
        if idx % 2 == 1 and (part.startswith("\\[") and part.endswith("\\]")):
            out.append(part)
            continue
        out.append(_escape_plain_tex(part))
    return "".join(out)
