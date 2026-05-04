from __future__ import annotations

import unittest

from backend.agent.core import SYSTEM_INSTRUCTIONS
from backend.llm.prompt_linter import lint_prompt_text
from backend.llm.prompts import create_llm_prompt_registry


class PromptLinterTests(unittest.TestCase):
    def test_agent_core_system_prompt_has_required_contracts(self) -> None:
        self.assertEqual(lint_prompt_text(SYSTEM_INSTRUCTIONS), [])

    def test_registered_system_prompts_have_required_contracts(self) -> None:
        registry = create_llm_prompt_registry()
        checked = 0
        for record in registry.list_prompts():
            if record.role != "system":
                continue
            issues = lint_prompt_text(record.content)
            self.assertEqual(issues, [], msg=f"{record.id}: {issues}")
            checked += 1

        self.assertGreaterEqual(checked, 10)


if __name__ == "__main__":
    unittest.main()
