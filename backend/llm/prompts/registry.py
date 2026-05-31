from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List

from backend.llm.prompts.agentic_registry import PromptRegistry, create_default_prompt_registry


def hash_prompt_content(content: str) -> str:
    return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LlmPromptRecord:
    id: str
    version: str
    role: str
    content: str
    content_hash: str
    schema: Dict[str, object]


class LlmPromptRegistry:
    """Stable LLM prompt registry facade.

    The underlying templates live in `backend.llm.prompts.agentic_registry`.
    This facade gives all LLM-facing domains one canonical place to inspect prompt
    identity, version, output schema, and rendered-content hash.
    """

    def __init__(self, source: PromptRegistry | None = None) -> None:
        self._source = source or create_default_prompt_registry()

    def render(self, prompt_id: str, **values: object) -> LlmPromptRecord:
        template = self._source.get(prompt_id)
        rendered = template.render(values)
        content_hash = rendered.content_hash or hash_prompt_content(rendered.content)
        return LlmPromptRecord(
            id=template.id,
            version=template.version,
            role=template.role,
            content=rendered.content,
            content_hash=content_hash,
            schema={
                "input_keys": list(template.input_keys),
                "output_contract": type(template.output_contract).__name__,
                "tags": list(template.tags),
            },
        )

    def list_prompts(self) -> List[LlmPromptRecord]:
        out: List[LlmPromptRecord] = []
        for template in self._source.list_templates():
            values = {key: "x" for key in template.input_keys}
            out.append(self.render(template.id, **values))
        return out


def create_llm_prompt_registry() -> LlmPromptRegistry:
    return LlmPromptRegistry()
