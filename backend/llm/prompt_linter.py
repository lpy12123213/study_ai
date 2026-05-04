from __future__ import annotations

from typing import Dict, List, Sequence

PROMPT_LINT_RULES: Dict[str, Sequence[str]] = {
    "persona": ("you are", "你是"),
    "output_format": (
        "output",
        "format",
        "return",
        "produce",
        "provide",
        "review",
        "summarize",
        "compress",
        "convert",
        "make",
        "输出",
    ),
    "language_policy": ("match the language", "language of the user's latest request", "语言"),
    "safety": ("do not", "never", "不要", "不得", "insufficient", "source"),
}


def lint_prompt_text(text: str) -> List[str]:
    raw = str(text or "").strip()
    lowered = raw.lower()
    issues: List[str] = []
    if not raw:
        return ["empty_prompt"]

    for rule, needles in PROMPT_LINT_RULES.items():
        if not any(str(needle).lower() in lowered for needle in needles):
            issues.append(f"missing_{rule}")
    return issues
