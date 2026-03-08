"""HTML parsers for extracting question data."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from bs4 import BeautifulSoup

from .utils import clean_html, parse_difficulty, parse_question_type


def parse_question_html(html_content: str) -> Dict[str, Any]:
    """Parse question from HTML content."""
    soup = BeautifulSoup(html_content, "html.parser")

    result = {
        "stem": "",
        "answer": None,
        "analysis": None,
        "question_type": None,
        "difficulty": None,
        "options": [],
    }

    # Try common selectors for question stem
    stem_selectors = [
        ".question-stem",
        ".stem",
        ".question-content",
        ".question-body",
        "[class*='stem']",
        "[class*='question']",
    ]

    for selector in stem_selectors:
        elem = soup.select_one(selector)
        if elem:
            result["stem"] = clean_html(str(elem))
            break

    # Try to find answer
    answer_selectors = [
        ".answer",
        ".question-answer",
        "[class*='answer']",
    ]

    for selector in answer_selectors:
        elem = soup.select_one(selector)
        if elem:
            result["answer"] = clean_html(str(elem))
            break

    # Try to find analysis
    analysis_selectors = [
        ".analysis",
        ".explanation",
        ".question-analysis",
        "[class*='analysis']",
        "[class*='explanation']",
    ]

    for selector in analysis_selectors:
        elem = soup.select_one(selector)
        if elem:
            result["analysis"] = clean_html(str(elem))
            break

    # Try to find options for choice questions
    option_selectors = [
        ".option",
        ".choice-option",
        "li[class*='option']",
    ]

    for selector in option_selectors:
        options = soup.select(selector)
        if options:
            result["options"] = [clean_html(str(opt)) for opt in options]
            break

    # Try to find difficulty
    difficulty_selectors = [
        ".difficulty",
        "[class*='difficulty']",
        "[class*='hard']",
    ]

    for selector in difficulty_selectors:
        elem = soup.select_one(selector)
        if elem:
            result["difficulty"] = parse_difficulty(elem.get_text())
            break

    # Try to find question type
    type_selectors = [
        ".question-type",
        "[class*='type']",
    ]

    for selector in type_selectors:
        elem = soup.select_one(selector)
        if elem:
            result["question_type"] = parse_question_type(elem.get_text())
            break

    return result


def parse_search_results(html_content: str) -> List[Dict[str, Any]]:
    """Parse search results from HTML content."""
    soup = BeautifulSoup(html_content, "html.parser")
    results = []

    # Try common selectors for search result items
    item_selectors = [
        ".search-result-item",
        ".question-item",
        ".result-item",
        "[class*='result']",
        "[class*='item']",
    ]

    items = []
    for selector in item_selectors:
        items = soup.select(selector)
        if items:
            break

    for item in items:
        result = {
            "id": "",
            "title": "",
            "preview": "",
            "url": "",
        }

        # Try to find link
        link = item.select_one("a")
        if link:
            result["url"] = link.get("href", "")
            result["title"] = clean_html(link.get_text())

        # Try to find ID
        item_id = item.get("data-id") or item.get("id")
        if item_id:
            result["id"] = str(item_id)
        elif result["url"]:
            # Try to extract ID from URL
            match = re.search(r"/(\d+)", result["url"])
            if match:
                result["id"] = match.group(1)

        # Try to find preview
        preview = item.select_one(".preview, .summary, .excerpt")
        if preview:
            result["preview"] = clean_html(preview.get_text())

        if result["id"]:
            results.append(result)

    return results
