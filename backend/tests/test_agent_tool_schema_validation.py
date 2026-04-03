from __future__ import annotations

import unittest

from backend.agent.tools.schemas import get_tool_input_schema
from backend.agent.tools.utils.schema_validation import validate_and_coerce_args


class TestAgentToolSchemaValidation(unittest.TestCase):
    def test_coerces_basic_types(self) -> None:
        schema = get_tool_input_schema("split_knowledge_points")
        out = validate_and_coerce_args(
            schema=schema,
            args={"topic": "导数", "min_points": "2", "max_points": "8"},
            tool_name="split_knowledge_points",
        )
        self.assertEqual(out["min_points"], 2)
        self.assertEqual(out["max_points"], 8)

    def test_rejects_wrong_container_types(self) -> None:
        schema = get_tool_input_schema("browse_web_pages")
        with self.assertRaises(ValueError):
            validate_and_coerce_args(schema=schema, args={"urls": "https://example.com"}, tool_name="browse_web_pages")

