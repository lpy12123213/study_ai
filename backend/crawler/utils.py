"""Utility functions for crawlers."""

from __future__ import annotations

import re
import html
from typing import Optional, List
from urllib.parse import urljoin, urlparse


def clean_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    # Decode HTML entities
    text = html.unescape(text)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_text_content(html_content: str) -> str:
    """Extract plain text from HTML content."""
    # Remove script and style elements
    html_content = re.sub(r"<script[^>]*>.*?</script>", "", html_content, flags=re.DOTALL)
    html_content = re.sub(r"<style[^>]*>.*?</style>", "", html_content, flags=re.DOTALL)
    return clean_html(html_content)


def normalize_url(url: str, base_url: str) -> str:
    """Normalize a URL relative to a base URL."""
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(base_url, url)


def extract_question_id(url: str) -> Optional[str]:
    """Extract question ID from a URL."""
    # Common patterns for question IDs
    patterns = [
        r"/question/(\d+)",
        r"/q/(\d+)",
        r"id=(\d+)",
        r"qid=(\d+)",
        r"/(\d+)\.html?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def parse_difficulty(text: str) -> Optional[float]:
    """Parse difficulty from text representation."""
    text = text.lower().strip()
    
    # Chinese difficulty names
    difficulty_map = {
        "容易": 0.2,
        "较易": 0.3,
        "简单": 0.2,
        "中等": 0.5,
        "较难": 0.7,
        "困难": 0.8,
        "难": 0.8,
    }
    
    for name, value in difficulty_map.items():
        if name in text:
            return value
    
    # Try to extract numeric value
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if match:
        value = float(match.group(1))
        # Normalize to 0-1 range
        if value > 1:
            value = value / 100 if value <= 100 else value / 1000
        return min(1.0, max(0.0, value))
    
    return None


def parse_question_type(text: str) -> Optional[str]:
    """Parse question type from text."""
    text = text.lower().strip()
    
    type_map = {
        "选择": "choice",
        "单选": "choice",
        "多选": "multiple_choice",
        "填空": "fill_blank",
        "解答": "short_answer",
        "简答": "short_answer",
        "论述": "essay",
        "计算": "calculation",
        "证明": "proof",
        "作图": "drawing",
    }
    
    for name, qtype in type_map.items():
        if name in text:
            return qtype
    
    return None


def split_into_sentences(text: str) -> List[str]:
    """Split text into sentences."""
    # Chinese and English sentence delimiters
    delimiters = r"[。！？!?]+"
    sentences = re.split(delimiters, text)
    return [s.strip() for s in sentences if s.strip()]


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate text to a maximum length."""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix
