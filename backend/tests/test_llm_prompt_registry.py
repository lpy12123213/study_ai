from __future__ import annotations

import unittest

from backend.llm.prompts import create_llm_prompt_registry, hash_prompt_content


class LlmPromptRegistryTests(unittest.TestCase):
    def test_registry_records_have_version_schema_and_hash(self) -> None:
        registry = create_llm_prompt_registry()
        records = registry.list_prompts()

        self.assertGreaterEqual(len(records), 20)
        for record in records:
            self.assertTrue(record.id)
            self.assertTrue(record.version)
            self.assertTrue(record.role)
            self.assertTrue(record.content)
            self.assertEqual(record.content_hash, hash_prompt_content(record.content))
            self.assertIn("output_contract", record.schema)
            self.assertIn("input_keys", record.schema)

    def test_registry_covers_current_llm_domains(self) -> None:
        ids = {record.id for record in create_llm_prompt_registry().list_prompts()}

        expected = {
            "agent.react.controller.v1",
            "agent.planner.study_materials.v1",
            "chat.paper_compose.system.v1",
            "deepthink.generator.v1",
            "lesson_plan.writer.v1",
            "mcp.paper_reviewer.v1",
            "question.draft.realize.v1",
            "study.material.writer.v1",
        }

        self.assertEqual(expected - ids, set())


if __name__ == "__main__":
    unittest.main()
