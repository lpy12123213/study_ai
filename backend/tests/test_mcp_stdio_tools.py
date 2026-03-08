import unittest


class TestMcpStdioTools(unittest.TestCase):
    def test_get_stdio_tools_contains_keyword_search(self) -> None:
        from backend.mcp.stdio_tools import get_stdio_tools

        tools = get_stdio_tools()
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 5)

        names = {getattr(t, "name", "") for t in tools}
        self.assertIn("search_questions_by_keyword", names)


if __name__ == "__main__":
    unittest.main()
