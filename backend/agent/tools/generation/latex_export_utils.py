from __future__ import annotations

import re
from typing import Any, List

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)


def _clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(min_value, min(max_value, n))


_BEGIN_BODY_RE = re.compile(r"%\s*---\s*BEGIN_BODY\s*---", re.IGNORECASE)
_END_BODY_RE = re.compile(r"%\s*---\s*END_BODY\s*---", re.IGNORECASE)
_BEGIN_BODY_LINE_RE = re.compile(r"(?im)^\s*%\s*---\s*BEGIN_BODY\s*---\s*$")
_END_BODY_LINE_RE = re.compile(r"(?im)^\s*%\s*---\s*END_BODY\s*---\s*$")
_LATEX_BEGIN_DOC = "\\begin{document}"
_LATEX_END_DOC = "\\end{document}"


def _strip_verbatim_like_blocks(text: str) -> str:
    s = text or ""
    try:
        s = re.sub(r"(?s)\\begin\{verbatim\}.*?\\end\{verbatim\}", "", s)
        s = re.sub(r"(?s)\\begin\{lstlisting\}.*?\\end\{lstlisting\}", "", s)
        s = re.sub(r"(?s)\\begin\{minted\}.*?\\end\{minted\}", "", s)
    except Exception:
        return text or ""
    return s


def _brace_balance(text: str) -> int:
    bal = 0
    s = text or ""
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n and s[i + 1] in "{}":
            i += 2
            continue
        if ch == "{":
            bal += 1
        elif ch == "}":
            bal -= 1
        if bal < 0:
            return bal
        i += 1
    return bal


def _strip_code_fences(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        first_newline = raw.find("\n")
        if first_newline != -1:
            raw = raw[first_newline + 1 :]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    return raw


def _clean_latex_body(body: str) -> str:
    text = (body or "").strip()
    if not text:
        return ""
    text = _BEGIN_BODY_LINE_RE.sub("", text)
    text = _END_BODY_LINE_RE.sub("", text)
    text = re.sub(r"(?im)^\s*\\maketitle\s*$", "", text)
    text = re.sub(r"(?im)^\s*\\documentclass\b.*$", "", text)
    text = re.sub(r"(?im)^\s*\\begin\{document\}\s*$", "", text)
    text = re.sub(r"(?im)^\s*\\end\{document\}\s*$", "", text)
    text = text.strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_latex_body(text: str) -> str:
    raw = _strip_code_fences(text)
    if not raw:
        return ""
    begin_matches = list(_BEGIN_BODY_RE.finditer(raw))
    if begin_matches:
        begin = begin_matches[-1]
        end = _END_BODY_RE.search(raw, pos=begin.end())
        if end:
            return _clean_latex_body(raw[begin.end() : end.start()])
        return _clean_latex_body(raw[begin.end() :])
    if _LATEX_BEGIN_DOC in raw:
        body = raw.split(_LATEX_BEGIN_DOC, 1)[1]
        if _LATEX_END_DOC in body:
            body = body.split(_LATEX_END_DOC, 1)[0]
        return _clean_latex_body(body)
    return _clean_latex_body(raw)


def _looks_truncated_latex_chunk(text: str, finish_reason: str, usage: Any, *, max_tokens: int) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if (finish_reason or "").strip().lower() == "length":
        return True
    if isinstance(usage, dict):
        try:
            ct = int(usage.get("completion_tokens") or 0)
        except Exception:
            ct = 0
        if ct and max_tokens and ct >= int(max_tokens * 0.95):
            return True
    if _LATEX_BEGIN_DOC in raw and _LATEX_END_DOC not in raw:
        return True
    if _BEGIN_BODY_RE.search(raw) and not _END_BODY_RE.search(raw):
        return True
    try:
        begins = len(re.findall(r"\\begin\{[^}]+\}", raw))
        ends = len(re.findall(r"\\end\{[^}]+\}", raw))
        if begins > ends:
            return True
    except Exception:
        logger.debug("latex_truncation_env_balance_check_failed", exc_info=True)
    raw_no_esc = re.sub(r"\\\$", "", raw)
    if raw_no_esc.count("$$") % 2 == 1:
        return True
    if raw_no_esc.replace("$$", "").count("$") % 2 == 1:
        return True
    try:
        raw_sans_verbatim = _strip_verbatim_like_blocks(raw)
        if _brace_balance(raw_sans_verbatim) != 0:
            return True
    except Exception:
        logger.debug("latex_truncation_brace_balance_check_failed", exc_info=True)
    tail = raw.rstrip()
    if tail and tail[-1] in {"\\", "{", "[", "(", "=", "+", "-", "$"}:
        return True
    return False


def _normalize_latex_text(text: str) -> str:
    s = text or ""
    if not s:
        return ""
    if s.count("\\n") >= 20 and s.count("\n") <= 3:
        s = s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    try:
        s = re.sub(r"\\\\(begin|end)\{", r"\\\1{", s)
        s = re.sub(r"\\\\(item)\b", r"\\\1", s)
        s = re.sub(r"\\\\(section|subsection|subsubsection|paragraph)\b", r"\\\1", s)
        s = re.sub(r"\\\\(includegraphics)\b", r"\\\1", s)
        s = re.sub(r"\\\\(textbf|textit|emph|mathrm|mathbf|mathit|mathcal)\b", r"\\\1", s)
    except Exception:
        return text or ""
    return s


def _looks_incomplete_latex(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if _LATEX_BEGIN_DOC in raw and _LATEX_END_DOC not in raw:
        return True
    if _BEGIN_BODY_RE.search(raw) and not _END_BODY_RE.search(raw):
        return True
    try:
        begins = len(re.findall(r"\\begin\{[^}]+\}", raw))
        ends = len(re.findall(r"\\end\{[^}]+\}", raw))
        if begins > ends:
            return True
    except Exception:
        logger.debug("latex_truncation_env_balance_check_failed", exc_info=True)
    raw_no_esc = re.sub(r"\\\$", "", raw)
    if raw_no_esc.count("$$") % 2 == 1:
        return True
    if raw_no_esc.replace("$$", "").count("$") % 2 == 1:
        return True
    try:
        raw_sans_verbatim = _strip_verbatim_like_blocks(raw)
        if _brace_balance(raw_sans_verbatim) != 0:
            return True
    except Exception:
        logger.debug("latex_truncation_brace_balance_check_failed", exc_info=True)
    tail = raw.rstrip()
    if tail and tail[-1] in {"\\", "{", "[", "(", "=", "+", "-", "$"}:
        return True
    return False


def _auto_fix_latex(text: str) -> str:
    s = _normalize_latex_text(text)
    if not s.strip():
        return ""

    suffix = ""
    if _LATEX_END_DOC in s:
        pre, post = s.split(_LATEX_END_DOC, 1)
        s = pre
        suffix = _LATEX_END_DOC + post

    s_no_verbatim = ""
    try:
        s_no_verbatim = _strip_verbatim_like_blocks(s)
    except Exception:
        s_no_verbatim = s

    try:
        bal = _brace_balance(s_no_verbatim)
    except Exception:
        bal = 0
    if bal > 0:
        s = s + ("}" * min(bal, 24))

    try:
        begins = list(re.finditer(r"\\begin\{([^}]+)\}", s))
        ends = list(re.finditer(r"\\end\{([^}]+)\}", s))
        if len(begins) > len(ends):
            stack: List[str] = []
            for m in re.finditer(r"\\(begin|end)\{([^}]+)\}", s):
                kind = m.group(1)
                name = m.group(2)
                if kind == "begin":
                    stack.append(name)
                else:
                    if stack and stack[-1] == name:
                        stack.pop()
                    elif name in stack:
                        while stack and stack[-1] != name:
                            stack.pop()
                        if stack and stack[-1] == name:
                            stack.pop()
            if stack:
                for name in reversed(stack[-24:]):
                    s = s.rstrip() + "\n\\end{" + name + "}"
    except Exception:
        logger.debug("latex_auto_fix_env_stack_failed", exc_info=True)

    try:
        raw_no_esc = re.sub(r"\\\$", "", s)
        if raw_no_esc.count("$$") % 2 == 1:
            s = s.rstrip() + "\n$$\n"
        if raw_no_esc.replace("$$", "").count("$") % 2 == 1:
            s = s.rstrip() + "$"
    except Exception:
        logger.debug("latex_auto_fix_math_delimiters_failed", exc_info=True)

    if suffix:
        if not s.endswith("\n"):
            s += "\n"
        s = s + suffix.lstrip("\n")
    return s

