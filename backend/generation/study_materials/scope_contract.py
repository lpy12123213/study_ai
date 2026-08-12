"""Deterministic parsing and inspection for scoped study-material output contracts."""

from __future__ import annotations

import re
from typing import Any, Dict, List

_EXTENSION_TOPICS_RE = re.compile(r"允许拓展仅限(?P<topics>.+?)。每项须用")
_MIN_KNOWLEDGE_SECTIONS_RE = re.compile(r"至少(?P<count>\d+)个独立知识点二级标题")
_ANY_EXTENSION_TAG_RE = re.compile(r"\[拓展\s*[:：][^\]\n]+\]")


def parse_extension_topics(requirements: str) -> List[str]:
    """Extract the exact controlled-extension topic names from a request contract."""

    match = _EXTENSION_TOPICS_RE.search(str(requirements or ""))
    if not match:
        return []
    seen: set[str] = set()
    topics: List[str] = []
    for raw in match.group("topics").split("、"):
        topic = raw.strip()
        if topic and topic not in seen:
            seen.add(topic)
            topics.append(topic)
    return topics


def parse_min_knowledge_sections(requirements: str) -> int:
    """Return the explicit minimum number of learner-visible knowledge sections."""

    match = _MIN_KNOWLEDGE_SECTIONS_RE.search(str(requirements or ""))
    return max(0, int(match.group("count"))) if match else 0


def inspect_extension_contract(markdown: str, topics: List[str]) -> Dict[str, Any]:
    """Require every exact extension tag to own a following high-school connection.

    A connection belongs to a topic only when it appears after that topic's tag and
    before the next extension tag. This prevents globally stacked marker tokens from
    satisfying several unrelated extensions.
    """

    required_topics = [str(topic).strip() for topic in topics if str(topic).strip()]
    if not required_topics:
        return {
            "required": False,
            "passed": True,
            "topic_hits": [],
            "connected_topics": [],
            "missing_topics": [],
            "missing_connections": [],
            "connection_count": 0,
            "required_count": 0,
            "ratio": 1.0,
        }

    text = str(markdown or "")
    topic_hits: List[str] = []
    connected_topics: List[str] = []
    for topic in required_topics:
        exact_pattern = re.compile(rf"\[拓展\s*[:：]\s*{re.escape(topic)}\s*\]")
        matches = list(exact_pattern.finditer(text))
        if not matches:
            continue
        topic_hits.append(topic)
        for match in matches:
            next_topic = _ANY_EXTENSION_TAG_RE.search(text, match.end())
            section_end = next_topic.start() if next_topic else len(text)
            if "[高中连接]" in text[match.end():section_end]:
                connected_topics.append(topic)
                break

    required_count = len(required_topics)
    ratio = len(connected_topics) / required_count
    return {
        "required": True,
        "passed": ratio >= 1.0,
        "topic_hits": topic_hits,
        "connected_topics": connected_topics,
        "missing_topics": [topic for topic in required_topics if topic not in topic_hits],
        "missing_connections": [topic for topic in topic_hits if topic not in connected_topics],
        "connection_count": len(re.findall(r"\[高中连接\]", text)),
        "required_count": required_count,
        "ratio": round(ratio, 4),
    }
