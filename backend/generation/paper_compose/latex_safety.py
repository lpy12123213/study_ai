from __future__ import annotations

import re


LATEX_BLOCKLIST_PATTERNS = [
    r"\\(?:input|include)\s*\{",
    r"\\openin\b",
    r"\\read\b",
    r"\\usepackage(?:\[[^\]]*\])?\s*\{[^}]*\b(?:catchfile|verbatim|fancyvrb|pythontex)\b[^}]*\}",
]


def ensure_latex_is_safe(tex: str) -> None:
    for pattern in LATEX_BLOCKLIST_PATTERNS:
        if re.search(pattern, tex, flags=re.IGNORECASE):
            raise ValueError("latex_unsafe_content")


_ensure_latex_is_safe = ensure_latex_is_safe
