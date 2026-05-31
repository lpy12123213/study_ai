"""Lightweight pre-processing for raw essay text.

Pure functions, no LLM calls. Splits an essay into paragraphs (CJK-aware),
counts characters / words and exposes a few structural metrics that the LLM
prompt can rely on (e.g. paragraph count, average sentence length) without
re-tokenizing the text on every call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


# Sentence terminators: full-width punctuation (CJK) and ASCII counterparts.
# Splits at the boundary right after the terminator regardless of whether the
# next character is whitespace, since CJK essays typically run sentences
# together without spaces.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;])\s*|\n+")
_PARAGRAPH_BOUNDARY = re.compile(r"\n\s*\n")
_WHITESPACE_RUN = re.compile(r"[ \t]+")
_WORD_TOKEN = re.compile(r"[A-Za-z]+|[\u4e00-\u9fff]")


@dataclass(slots=True)
class EssayParagraph:
    """A normalized paragraph entry."""

    index: int
    text: str
    char_count: int
    sentence_count: int


@dataclass(slots=True)
class ParsedEssay:
    """Container returned by :func:`parse_essay`.

    The fields are the minimum the LLM prompt + UI heatmap need; everything
    else can be derived on the fly.
    """

    raw: str
    cleaned: str
    paragraphs: List[EssayParagraph]
    char_count: int
    word_count: int
    sentence_count: int
    paragraph_count: int
    language_hint: str  # "zh" / "en" (best-effort)


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of horizontal whitespace and trim trailing spaces.

    Keeps explicit ``\\n`` boundaries so paragraph splitting still works.
    """

    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in text.split("\n"):
        line = _WHITESPACE_RUN.sub(" ", line).rstrip()
        lines.append(line)
    return "\n".join(lines).strip()


def _detect_language(text: str) -> str:
    """Best-effort language hint based on CJK character ratio."""

    if not text:
        return "zh"
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    ascii_letters = len(re.findall(r"[A-Za-z]", text))
    if cjk == 0 and ascii_letters > 0:
        return "en"
    if ascii_letters > cjk * 3:
        return "en"
    return "zh"


def _count_sentences(text: str) -> int:
    if not text:
        return 0
    parts = [p for p in _SENTENCE_BOUNDARY.split(text) if p and p.strip()]
    return max(len(parts), 1)


def _count_words(text: str, *, language: str) -> int:
    if not text:
        return 0
    if language == "en":
        return len([token for token in re.split(r"\s+", text) if token.strip()])
    # CJK: count 字 + 拉丁词 as separate units, mirroring 字数 conventions.
    return len(_WORD_TOKEN.findall(text))


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #


def parse_essay(text: str) -> ParsedEssay:
    """Split an essay into paragraphs and compute structural metrics."""

    cleaned = _normalize_whitespace(text or "")
    if not cleaned:
        return ParsedEssay(
            raw=text or "",
            cleaned="",
            paragraphs=[],
            char_count=0,
            word_count=0,
            sentence_count=0,
            paragraph_count=0,
            language_hint="zh",
        )

    language = _detect_language(cleaned)

    raw_paragraphs = [p.strip() for p in _PARAGRAPH_BOUNDARY.split(cleaned) if p.strip()]
    if not raw_paragraphs:
        raw_paragraphs = [cleaned]

    paragraphs: List[EssayParagraph] = []
    for idx, para in enumerate(raw_paragraphs):
        paragraphs.append(
            EssayParagraph(
                index=idx,
                text=para,
                char_count=len(para),
                sentence_count=_count_sentences(para),
            )
        )

    return ParsedEssay(
        raw=text or "",
        cleaned=cleaned,
        paragraphs=paragraphs,
        char_count=sum(p.char_count for p in paragraphs),
        word_count=_count_words(cleaned, language=language),
        sentence_count=sum(p.sentence_count for p in paragraphs),
        paragraph_count=len(paragraphs),
        language_hint=language,
    )


__all__ = ["EssayParagraph", "ParsedEssay", "parse_essay"]
