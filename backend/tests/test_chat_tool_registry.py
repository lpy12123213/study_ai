from __future__ import annotations

import inspect
import unittest
from unittest.mock import AsyncMock, patch

from backend.chat.service import ChatService
from backend.chat.tool_registry import ChatToolRegistry
from backend.chat.tools_mixin import ChatToolsMixin
from backend.chat.tools_spec import TOOLS


class ChatToolRegistryTests(unittest.IsolatedAsyncioTestCase):
    def test_registry_loads_specs_and_schemas_by_name(self) -> None:
        registry = ChatToolRegistry(TOOLS)
        names = registry.names()

        self.assertIn("search_questions", names)
        self.assertIn("create_paper", names)
        self.assertEqual(
            registry.schema_for("create_paper")["required"],
            ["paper_name", "question_ids"],
        )

        subset = registry.specs(["create_paper", "missing"])
        self.assertEqual(len(subset), 1)
        self.assertEqual(subset[0]["function"]["name"], "create_paper")

    def test_chat_mixin_uses_registry_for_tool_lookup(self) -> None:
        service = ChatService()

        specs = service._tools_by_names(["search_questions", "get_papers", "missing"])
        self.assertEqual([spec["function"]["name"] for spec in specs], ["search_questions", "get_papers"])
        self.assertIn("properties", service._lookup_tool_schema("search_questions"))

    async def test_execute_tool_dispatches_through_registered_handler(self) -> None:
        service = ChatService()
        save_paper = AsyncMock(return_value=321)

        with patch("backend.chat.tools_mixin.save_paper", save_paper):
            result = await service.execute_tool(
                "create_paper",
                {"paper_name": "测试卷", "question_ids": '["q1", "q2"]'},
                user_id="user-1",
            )

        self.assertEqual(result["paper_id"], 321)
        save_paper.assert_awaited_once_with(
            user_id="user-1",
            paper_name="测试卷",
            questions=[{"question_id": "q1"}, {"question_id": "q2"}],
        )

    async def test_execute_tool_reports_unknown_tool(self) -> None:
        result = await ChatService().execute_tool("missing_tool", {}, user_id="user-1")

        self.assertEqual(result["success"], False)
        self.assertIn("未知工具", result["error"])

    def test_execute_tool_no_longer_hardcodes_tool_name_branch_table(self) -> None:
        source = inspect.getsource(ChatToolsMixin.execute_tool)

        self.assertNotIn('tool_name == "', source)
        self.assertIn("_chat_tool_registry", source)


if __name__ == "__main__":
    unittest.main()
