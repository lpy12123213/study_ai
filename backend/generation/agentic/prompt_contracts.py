from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    raw = str(text or "").lower()
    return any(n.lower() in raw for n in needles)


def _requests_hidden_chain_of_thought(text: str) -> bool:
    raw = str(text or "").lower()
    if not _has_any(raw, ("逐步思考", "完整思维链", "chain-of-thought", "隐藏推理")):
        return False
    return not _has_any(raw, ("不要输出完整思维链", "不要输出完整", "不要", "禁止", "do not", "don't"))


@dataclass(frozen=True)
class JsonOutputContract:
    """Contract for prompts that require machine-readable JSON output."""

    json_object: bool = True
    schema_hint: Dict[str, str] = field(default_factory=dict)

    def validate_prompt_text(self, text: str) -> List[str]:
        issues: List[str] = []
        if not _has_any(text, ("json", "JSON")):
            issues.append("missing_json_constraint")
        if not _has_any(
            text,
            (
                "不要输出 Markdown",
                "禁止 Markdown",
                "不要 Markdown",
                "no markdown",
                "do not output markdown",
                "not markdown",
            ),
        ):
            issues.append("missing_no_markdown_constraint")
        if not _has_any(text, ("代码块", "code fence", "code block", "```")):
            issues.append("missing_no_code_fence_constraint")
        if _requests_hidden_chain_of_thought(text):
            issues.append("requests_hidden_chain_of_thought")
        return issues

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": "json",
            "json_object": bool(self.json_object),
            "schema_hint": dict(self.schema_hint),
        }


@dataclass(frozen=True)
class MarkdownOutputContract:
    """Contract for prompts that produce Markdown for users."""

    educational_writing: bool = False
    allow_urls: bool = False

    def validate_prompt_text(self, text: str) -> List[str]:
        issues: List[str] = []
        if not _has_any(text, ("markdown", "Markdown")):
            issues.append("missing_markdown_constraint")
        if self.educational_writing:
            if not _has_any(
                text,
                (
                    "原创改写",
                    "自己的话",
                    "不得复制",
                    "严禁照抄",
                    "重新组织",
                    "original rewrite",
                    "original rewrites",
                    "own words",
                    "do not copy",
                    "not copy",
                ),
            ):
                issues.append("missing_original_rewrite_constraint")
            if not self.allow_urls and not _has_any(
                text,
                (
                    "不输出 URL",
                    "不要输出 URL",
                    "不输出任何 URL",
                    "no url",
                    "must not include urls",
                    "do not output urls",
                    "do not include urls",
                    "external links",
                ),
            ):
                issues.append("missing_no_url_constraint")
            if not _has_any(text, ("来源", "source", "素材", "证据", "ground")):
                issues.append("missing_source_grounding_constraint")
        if _requests_hidden_chain_of_thought(text):
            issues.append("requests_hidden_chain_of_thought")
        return issues

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": "markdown",
            "educational_writing": bool(self.educational_writing),
            "allow_urls": bool(self.allow_urls),
        }
