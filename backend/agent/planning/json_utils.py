from __future__ import annotations

from typing import Any, Dict

from backend.llm.json_utils import extract_first_json_object


def _extract_json_obj(text: str) -> Dict[str, Any]:
    return extract_first_json_object(text, default={}) or {}
