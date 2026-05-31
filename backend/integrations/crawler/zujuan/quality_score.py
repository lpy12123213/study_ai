"""Heuristic quality scoring for Zujuan-crawled questions.

Pulled out of the (long) ``client.py`` because the rules don't depend on any
crawler instance state – they only inspect the structured ``question`` dict.
Keeping the heuristics in their own module makes them straightforward to
unit-test and lets us iterate on the scoring logic without scrolling through
the full crawler implementation.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

_STOPWORDS = frozenset(
    {
        "函数",
        "方程",
        "不等式",
        "几何",
        "代数",
        "解析几何",
        "概率",
        "统计",
        "综合",
        "应用",
        "证明",
        "计算",
        "解答",
    }
)

_OPTION_LABEL_RE = re.compile(r"(?:^|[\s\r\n{};；])([A-H])\s*(?:[\.．、\)）:：])")


def _choice_option_count(stem: str) -> int:
    labels = _OPTION_LABEL_RE.findall(stem or "")
    return len({x.upper() for x in labels if x})


def _looks_like_choice_prompt(stem: str) -> bool:
    text = re.sub(r"\s+", " ", stem or "").strip()
    if not text:
        return False

    has_empty_choice_blank = bool(re.search(r"[（(]\s*[\u3000\s]*[)）]", text))
    choice_words = (
        "下列",
        "正确",
        "错误",
        "可能",
        "不可能",
        "符合",
        "不符合",
        "选项",
        "标号",
        "序号",
        "则",
        "应",
        "是",
        "为",
    )
    if has_empty_choice_blank and any(word in text for word in choice_words):
        return True
    if re.search(r"(?:下列|以下).{0,30}(?:正确|错误|可能|不可能|符合|不符合|是|为)", text):
        return True
    if re.search(r"填(?:正确)?(?:答案)?(?:标号|序号|字母)", text):
        return True
    return False


def quality_score(question: Dict[str, Any]) -> Tuple[int, List[str]]:
    """Score a Zujuan question dict in [0, 100] and return (score, flags).

    Flags are short snake_case tokens describing the issue that lowered the
    score (e.g. ``"stem_too_short"``); the API surfaces them so the question
    library UI can highlight problems without re-running the heuristics.
    """

    stem = (question.get("stem") or "").strip()
    if not stem:
        return 0, ["missing_stem"]

    flags: List[str] = []
    score = 100
    qtype = str(question.get("type") or "").strip()
    is_choice = any(x in qtype for x in ("单选", "多选", "选择"))
    looks_like_choice = is_choice or _looks_like_choice_prompt(stem)

    stem_len = len(stem)
    if stem_len < 20:
        flags.append("stem_too_short")
        score -= 70
    elif stem_len < 60:
        flags.append("stem_short")
        score -= 30

    unknown_tokens = len(re.findall(r"\[\?[0-9a-fA-F]{4,}\]", stem))
    if unknown_tokens > 0:
        flags.append(f"unknown_tokens:{unknown_tokens}")
        score -= min(unknown_tokens * 15, 60)

    image_tokens = stem.count("[图片:")
    if image_tokens > 0:
        flags.append(f"has_images:{image_tokens}")
        score -= min(image_tokens * 10, 40)

    formula_placeholders = stem.count("[公式:")
    if formula_placeholders > 0:
        flags.append(f"formula_unconverted:{formula_placeholders}")
        score -= min(formula_placeholders * 15, 60)

    if "(需登录查看)" in stem:
        flags.append("login_required_content")
        score -= 30

    # Choice questions should include options; missing/incomplete options usually means truncated HTML.
    if looks_like_choice:
        opt_count = _choice_option_count(stem)
        if opt_count <= 0:
            flags.append("choice_missing_options")
            score -= 35
        elif opt_count < 4:
            flags.append(f"choice_options_incomplete:{opt_count}")
            score -= min((4 - opt_count) * 8, 24)
        else:
            flags.append(f"choice_options:{opt_count}")

    # Language completeness / readability heuristics.
    if stem_len >= 80:
        cjk = len(re.findall(r"[\u4e00-\u9fff]", stem))
        wordlike = cjk + len(re.findall(r"[A-Za-z0-9]", stem))
        if wordlike > 0:
            punct = max(0, stem_len - wordlike)
            if punct / max(1, stem_len) > 0.70:
                flags.append("language_noisy")
                score -= 12

    # Dangling punctuation often indicates truncation (except when followed by options in choice questions).
    if (not is_choice) and re.search(r"[，,、;；:：]$", stem):
        flags.append("stem_dangling_punct")
        score -= 8

    # Unbalanced brackets/parentheses are common when HTML/text is truncated.
    for open_c, close_c, name in (("(", ")", "paren"), ("（", "）", "cjk_paren"), ("[", "]", "bracket")):
        if stem.count(open_c) != stem.count(close_c):
            flags.append(f"unbalanced_{name}")
            score -= 8
            break

    # Knowledge point match: basic keyword overlap between kp names and stem.
    kps_raw = question.get("knowledge_points") or []
    if isinstance(kps_raw, str):
        kp_list = [x.strip() for x in re.split(r"[，,;；/\\s]+", kps_raw) if x.strip()]
    elif isinstance(kps_raw, list):
        kp_list = [str(x or "").strip() for x in kps_raw if str(x or "").strip()]
    else:
        kp_list = []

    keywords: List[str] = []
    seen_kw: set[str] = set()
    for kp in kp_list[:10]:
        parts = re.findall(r"[\u4e00-\u9fff]{2,}", kp)
        for part in parts:
            kw = part.strip()
            if len(kw) < 3:
                continue
            if not kw or kw in _STOPWORDS:
                continue
            if kw in seen_kw:
                continue
            seen_kw.add(kw)
            keywords.append(kw)
            if len(keywords) >= 10:
                break
        if len(keywords) >= 10:
            break

    if keywords:
        hits = sum(1 for kw in keywords if kw in stem)
        if hits <= 0:
            flags.append("kp_match_low")
            score -= 10

    score = max(0, min(100, score))
    return score, flags


__all__ = ["quality_score"]
