from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from backend.core.text_utils import clip_text as _clip_text

_PDF_URL_RE = re.compile(r"\.pdf(?:$|[?#])", re.IGNORECASE)


def _looks_like_pdf_url(url: str) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    try:
        path = (urlparse(u).path or "").lower()
        if path.endswith(".pdf"):
            return True
    except ValueError:
        return bool(_PDF_URL_RE.search(u))
    return bool(_PDF_URL_RE.search(u))


# Domain credibility table for source ranking in study-material generation.
# Higher = more trustworthy. Lookup is suffix-based (e.g. "wiki.example.edu.cn" matches "edu.cn").
# Curated for K-12 / Gaokao Chinese context; tweak via STUDY_MATERIALS_DOMAIN_WEIGHTS if needed.
_DOMAIN_CREDIBILITY: Tuple[Tuple[str, float], ...] = (
    # Government / official curricular sources
    ("moe.gov.cn", 0.98),
    ("pep.com.cn", 0.95),  # 人教社
    ("ncct.gov.cn", 0.95),
    ("edu.cn", 0.85),
    ("gov.cn", 0.85),
    # University-hosted educational material
    ("bnu.edu.cn", 0.85),
    ("tsinghua.edu.cn", 0.85),
    ("pku.edu.cn", 0.85),
    ("ecnu.edu.cn", 0.82),
    # Encyclopedia / reference
    ("zh.wikipedia.org", 0.85),
    ("en.wikipedia.org", 0.85),
    ("britannica.com", 0.85),
    ("baike.baidu.com", 0.65),
    # Exam / problem aggregators (authoritative content but may include user uploads)
    ("zujuan.xkw.com", 0.75),
    ("xkw.com", 0.7),
    ("21cnjy.com", 0.7),
    ("zxxk.com", 0.65),
    # General Q&A / blogs (mixed quality)
    ("zhuanlan.zhihu.com", 0.55),
    ("zhihu.com", 0.5),
    ("csdn.net", 0.45),
    ("jianshu.com", 0.4),
    ("cnblogs.com", 0.45),
    # Search-result spam / low-trust aggregators
    ("docin.com", 0.25),
    ("doc88.com", 0.25),
    ("doczj.com", 0.25),
    ("wenku.baidu.com", 0.3),
    ("max.book118.com", 0.25),
)

_DOMAIN_DEFAULT_CREDIBILITY = 0.45


def _extract_domain(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        netloc = urlparse(raw).netloc.lower()
    except ValueError:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _credibility_for_domain(domain: str) -> float:
    if not domain:
        return _DOMAIN_DEFAULT_CREDIBILITY
    d = domain.lower()
    for suffix, score in _DOMAIN_CREDIBILITY:
        if d == suffix or d.endswith("." + suffix):
            return score
    return _DOMAIN_DEFAULT_CREDIBILITY


def credibility_for_url(url: str) -> Tuple[str, float]:
    """Public helper: return (domain, credibility_score) for a given URL.

    Suffix matches a curated table; defaults to 0.45 for unknown domains.
    """

    domain = _extract_domain(url)
    return domain, _credibility_for_domain(domain)


def _compact_snippet(text: str, *, max_chars: int = 400) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    # Collapse all whitespace (including newlines) into a single line to avoid polluting Markdown bullets.
    compact = re.sub(r"\s+", " ", raw.replace("\u00a0", " ")).strip()
    return _clip_text(compact, max_chars=max_chars)


def _strip_evidence_markers(text: str) -> str:
    """Remove common inline evidence markers like `[[1]]` that some providers include."""

    raw = (text or "").strip()
    if not raw:
        return ""
    # Remove parenthesized markers first to avoid leaving empty `()` behind.
    raw = re.sub(r"\(\s*\[\[\s*\d+\s*\]\]\s*\)", "", raw)
    raw = re.sub(r"\[\[\s*\d+\s*\]\]", "", raw)
    # Collapse excessive whitespace after removals.
    # IMPORTANT: keep newlines (Markdown structure), only collapse horizontal spaces/tabs.
    raw = re.sub(r"[ \t]{2,}", " ", raw).strip()
    return raw


_UI_NOISE_EXACT = {
    "播报",
    "编辑",
    "登录",
    "注册",
    "目录",
    "导航",
    "首页",
    "帮助",
    "反馈",
    "免责声明",
    "隐私",
    "用户协议",
    "关于我们",
    "联系我们",
    "加入我们",
    "企业推广",
    "广告",
    "推广",
    "分享",
    "收藏",
}

_UI_NOISE_SUBSTRINGS = (
    "©",
    "版权所有",
    "版权",
    "ICP备",
    "备案",
    "Baidu",
    "Sogou",
    "百度",
    "搜狗",
)


def _is_ui_noise_line(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return True

    if s in _UI_NOISE_EXACT and len(s) <= 8:
        return True

    if any(token in s for token in ("免责声明", "隐私", "用户协议")) and len(s) <= 50:
        return True

    lower = s.lower()
    if ("baidu" in lower or "sogou" in lower) and any(x in s for x in ("©", "版权", "版权所有")):
        return True

    # Cookie / consent banners and sign-in gates are extremely common "junk" around extracted content.
    if (
        ("cookie" in lower or "cookies" in lower)
        and len(s) <= 200
        and any(
            tok in lower
            for tok in (
                "we use",
                "use cookies",
                "policy",
                "consent",
                "preferences",
                "privacy",
                "使用",
                "同意",
                "拒绝",
                "隐私",
                "条款",
                "政策",
            )
        )
    ):
        return True
    if ("enable javascript" in lower or ("javascript" in lower and "enable" in lower)) and len(s) <= 160:
        return True
    if any(tok in lower for tok in ("sign in", "log in", "subscribe")) and len(s) <= 120:
        return True
    if (
        any(tok in s for tok in ("验证码", "机器人验证", "请启用JavaScript", "启用JavaScript", "请开启JavaScript"))
        and len(s) <= 80
    ):
        return True
    if any(tok in s for tok in ("登录后", "请登录", "注册后", "注册")) and len(s) <= 60:
        return True

    if any(sub in s for sub in _UI_NOISE_SUBSTRINGS) and len(s) <= 60:
        return True

    if re.fullmatch(r"©?\s*\d{4}.*", s) and len(s) <= 80:
        return True

    return False


def _remove_ui_noise(text: str, *, max_lines: int = 400) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    lines: List[str] = []
    last = ""
    for ln in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        s = (ln or "").strip()
        if _is_ui_noise_line(s):
            continue
        if s == last:
            continue
        last = s
        lines.append(s)
        if len(lines) >= max_lines:
            break
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _sanitize_explanation_markdown(markdown: str, *, knowledge_point: str) -> str:
    """Normalize generated Markdown so it fits under `### 核心讲解`.

    The LLM sometimes outputs:
    - top-level headings (`# ...`) which break the final archive structure
    - a duplicated "参考资料/外部链接" block (we render sources separately)
    - raw URLs or evidence markers like `[[1]]`
    """

    text = (markdown or "").strip()
    if not text:
        return ""

    text = _strip_evidence_markers(text)

    # If the model inserted a references section, truncate it (the archive already lists sources).
    ref_pat = re.compile(r"(?im)^(#{1,6}\s*)?(参考资料|参考文献|外部链接|references)\b.*$")
    m = ref_pat.search(text)
    if m:
        text = text[: m.start()].rstrip()

    # Replace markdown links with titles, then drop remaining raw URLs.
    text = re.sub(r"\[([^\]]+)\]\(https?://[^\)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)

    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    def _norm_title(s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"自学讲解|自学|讲解|概念", "", s)
        s = re.sub(r"[\s:：—\\-–·•,，。！？()（）《》“”\"'’]+", "", s)
        return s

    kp_norm = _norm_title(knowledge_point)
    first_non_empty = next((i for i, ln in enumerate(raw_lines) if (ln or "").strip()), None)
    if first_non_empty is not None and kp_norm:
        m0 = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", raw_lines[first_non_empty] or "")
        if m0:
            title = _norm_title(m0.group(2) or "")
            if title and (kp_norm in title or title in kp_norm):
                raw_lines[first_non_empty] = ""

    out_lines: List[str] = []
    for ln in raw_lines:
        s = ln.rstrip()
        # Explanation is rendered under a level-3 heading, so we keep headings at level>=4.
        m_h = re.match(r"^(\s*)(#{1,6})(\s+)(.*)$", s)
        if m_h:
            indent, hashes, space, rest = m_h.groups()
            lvl = len(hashes)
            if lvl <= 3:
                hashes = "####"
                s = f"{indent}{hashes}{space}{rest}".rstrip()
        out_lines.append(s)

    cleaned = "\n".join(out_lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _has_unclosed_code_fence(text: str) -> bool:
    fences = re.findall(r"(^|\n)```", text)
    return len(fences) % 2 == 1


def _has_unbalanced_inline_math(text: str) -> bool:
    # Rough heuristic: ignore escaped \$ and count remaining "$".
    raw = re.sub(r"\\\$", "", text)
    return raw.count("$") % 2 == 1


def _looks_truncated_markdown(text: str) -> bool:
    raw = (text or "").rstrip()
    if not raw:
        return False
    if _has_unclosed_code_fence(raw):
        return True
    if raw.count("$$") % 2 == 1:
        return True
    if _has_unbalanced_inline_math(raw):
        return True
    last = raw[-1]
    if last in {"-", "—", "(", "（", "[", "{", "=", "+", "*", "/", "\\", "$"}:
        return True
    return False


def _trim_overlap(prefix: str, addition: str, *, max_check: int = 480) -> str:
    if not prefix or not addition:
        return addition
    p = prefix[-max_check:]
    a = addition[:max_check]
    max_k = min(len(p), len(a))
    for k in range(max_k, 24, -1):
        if p.endswith(a[:k]):
            return addition[k:]
    return addition


def _repair_incomplete_markdown(text: str) -> str:
    raw = (text or "").rstrip()
    if not raw:
        return ""
    if _has_unclosed_code_fence(raw):
        raw = raw + "\n```"
    if raw.count("$$") % 2 == 1:
        raw = raw + "\n$$"
    if _has_unbalanced_inline_math(raw):
        raw = raw + "$"
    return raw


def _postprocess_web_search_result(result: Dict[str, Any], *, max_snippet_chars: int = 400) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(result or {})

    # Metaso /ask snippets sometimes contain evidence markers like [[1]]; strip them early so the
    # downstream LLM won't copy them into the final study material.
    for k in ("title", "snippet", "text", "summary"):
        if isinstance(out.get(k), str) and out.get(k):
            out[k] = _strip_evidence_markers(str(out.get(k) or ""))

    # Normalize Exa highlights (list[str]) into a compact, UI-noise-filtered form.
    if isinstance(out.get("highlights"), list):
        cleaned_h: List[str] = []
        for h in out.get("highlights") or []:
            if not isinstance(h, str):
                continue
            s = _strip_evidence_markers(h)
            s = _remove_ui_noise(s, max_lines=40)
            s = _compact_snippet(s, max_chars=260)
            if s:
                cleaned_h.append(s)
            if len(cleaned_h) >= 6:
                break
        out["highlights"] = cleaned_h

    url = str(out.get("url") or out.get("link") or "").strip()
    if url and not str(out.get("url") or "").strip():
        out["url"] = url

    domain, credibility = credibility_for_url(url)
    if domain:
        out.setdefault("domain", domain)
    out["credibility_score"] = round(credibility, 3)

    if _looks_like_pdf_url(url):
        # Avoid injecting garbled "PDF text" into the archive (common for math formulas).
        out["content_type_hint"] = "application/pdf"
        flags = list(out.get("quality_flags") or []) if isinstance(out.get("quality_flags"), list) else []
        if "pdf_unreadable" not in flags:
            flags.append("pdf_unreadable")
        out["quality_flags"] = flags
        # Downweight unreadable PDFs so synthesizer prefers other sources first.
        out["credibility_score"] = round(min(out["credibility_score"], 0.25), 3)
        pdf_summary = _remove_ui_noise(str(out.get("summary") or ""))
        if pdf_summary:
            out["summary"] = _clip_text(_compact_snippet(pdf_summary, max_chars=1200), max_chars=1200)
            out["snippet"] = _compact_snippet(pdf_summary, max_chars=max_snippet_chars)
        else:
            out["snippet"] = "[PDF课件]（为避免公式/符号乱码，已省略正文抽取；建议打开链接查看）"
        out["text"] = ""
        return out

    text = _remove_ui_noise(str(out.get("text") or ""))
    snippet = _remove_ui_noise(str(out.get("snippet") or ""))
    summary = _remove_ui_noise(str(out.get("summary") or ""))

    if not snippet and summary:
        out["snippet"] = _compact_snippet(summary, max_chars=max_snippet_chars)
    elif not snippet and isinstance(out.get("highlights"), list) and out.get("highlights"):
        joined = " ".join([str(x or "").strip() for x in (out.get("highlights") or []) if str(x or "").strip()])
        out["snippet"] = _compact_snippet(joined, max_chars=max_snippet_chars)
    elif not snippet and text:
        out["snippet"] = _compact_snippet(text, max_chars=max_snippet_chars)
    elif snippet:
        out["snippet"] = _compact_snippet(snippet, max_chars=max_snippet_chars)

    # Keep the original `text` (if any) but also normalize excessive whitespace.
    if text:
        out["text"] = _clip_text(text, max_chars=8000)
    if summary:
        out["summary"] = _clip_text(_compact_snippet(summary, max_chars=1200), max_chars=1200)
    return out
