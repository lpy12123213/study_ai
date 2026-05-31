from __future__ import annotations

import unittest


class PaperComposeAgentToolRegistrationTests(unittest.TestCase):
    def test_executor_registers_paper_compose_agent_tools(self) -> None:
        from backend.agent.executor import Executor

        expected_tools = {
            "crawl_questions_from_bank",
            "generate_questions_ai",
            "solve_question_independently",
            "render_paper_latex",
            "compile_latex_sandbox",
            "repair_latex",
        }

        registered = {tool["name"] for tool in Executor().tool_registry.list_tools()}
        self.assertTrue(expected_tools.issubset(registered))


if __name__ == "__main__":
    unittest.main()
