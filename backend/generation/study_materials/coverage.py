"""按知识点拆分 Markdown 小节并评估覆盖维度的共享助手。

供 content_review 工具与 study_materials 质量门共用，避免两处各抄一份
`md_sections_by_kp` / 维度正则逻辑。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# 自学资料正文按二级标题（## N、知识点）划分知识点小节；
# 标题匹配是宽松的：去掉编号/标点、大小写归一后做子串匹配。
_KP_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
_HEADING_NUMBERING_RE = re.compile(r"^\s*\d+\s*[、.．)]\s*")
_HEADING_PUNCT_RE = re.compile(r"[\s\-—–_*#:：,，;；()（）\[\]【】<>《》]+")

# 9 个内容维度的词表正则（与 content_review 历史实现保持一致）。
DIMENSION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("动机/直观", r"(动机|为什么|意义|背景|直观|intuition|引入|起源|由来|缘由)"),
    ("定义/概念", r"(定义|概念|是什么|含义|本质|内涵|外延|界定)"),
    ("性质/结论", r"(性质|结论|定理|推论|关键结论|重要结论|特点|特性|规律|法则)"),
    ("条件/适用范围", r"(条件|适用|前提|范围|成立|约束|限制|假设|要求)"),
    ("反例/边界", r"(反例|边界|极端|陷阱|特例|例外|临界|极限情况)"),
    ("误区/易错点", r"(误区|易错|注意|常见错误|混淆|辨析|区分|对比)"),
    ("应用/题型", r"(应用|题型|例题|典型|场景|实例|案例|练习|解题)"),
    ("推导/证明", r"(推导|证明|演算|论证|证法|步骤)"),
    ("联系/拓展", r"(联系|拓展|延伸|相关|对比|类比|推广|深入)"),
)


def _normalize_heading_text(value: Any) -> str:
    text = str(value or "").strip()
    text = _HEADING_NUMBERING_RE.sub("", text)
    text = _HEADING_PUNCT_RE.sub("", text)
    return text.casefold()


def split_sections_by_kp(markdown: str, kp_titles: List[str]) -> Dict[str, str]:
    """Split Markdown level-2 sections and attribute them to knowledge-point titles.

    返回 ``{kp_title: section_body}``；标题未匹配到任何小节的知识点映射到
    空字符串（即 "unmatched" 结果，调用方必须显式处理，不能当作已覆盖）。
    """

    sections: List[tuple[str, str]] = []
    current_heading = ""
    buf: List[str] = []
    started = False
    for line in str(markdown or "").splitlines():
        match = _KP_HEADING_RE.match(line.strip())
        if match:
            if started:
                sections.append((current_heading, "\n".join(buf).strip()))
            current_heading = str(match.group(1) or "").strip()
            buf = []
            started = True
            continue
        if started:
            buf.append(line)
    if started:
        sections.append((current_heading, "\n".join(buf).strip()))

    result: Dict[str, str] = {}
    used: set[int] = set()
    for raw_title in kp_titles:
        title = str(raw_title or "").strip()
        matched_body = ""
        norm_title = _normalize_heading_text(title)
        if norm_title:
            for index, (heading, body) in enumerate(sections):
                if index in used:
                    continue
                norm_heading = _normalize_heading_text(heading)
                if norm_heading and (norm_title in norm_heading or norm_heading in norm_title):
                    matched_body = body
                    used.add(index)
                    break
        result[title] = matched_body
    return result


def unmatched_kp_titles(sections_by_kp: Dict[str, str]) -> List[str]:
    """Return the kp titles whose section lookup came back empty (unmatched)."""

    return [title for title, body in (sections_by_kp or {}).items() if not str(body or "").strip()]


def evaluate_kp_dimensions(section: str) -> Dict[str, List[str]]:
    """Evaluate the 9 content dimensions against one knowledge-point section."""

    text = str(section or "")
    present: List[str] = []
    missing: List[str] = []
    for name, pattern in DIMENSION_PATTERNS:
        if re.search(pattern, text):
            present.append(name)
        else:
            missing.append(name)
    return {"present": present, "missing": missing}
