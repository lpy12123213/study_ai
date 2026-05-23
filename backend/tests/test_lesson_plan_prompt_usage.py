from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.generation.agentic.prompts import create_default_prompt_registry


class LessonPlanPromptUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_planning_prompts_use_registry(self) -> None:
        from backend.generation.lesson_plan import planning

        captured: list[str] = []

        async def fake_call_llm_text(*, messages, **_kwargs):  # type: ignore[no-untyped-def]
            captured.append(str(messages[0]["content"]))
            return '{"knowledge_points":["A","B","C"],"teaching_points":["t"],"common_misconceptions":[],"suggested_activities":[],"key_examples":[]}'

        registry = create_default_prompt_registry()

        with patch("backend.generation.lesson_plan.planning.call_llm_text", new=fake_call_llm_text):
            await planning.split_knowledge_points("函数", "高中数学", min_points=1, max_points=3)
            await planning.research_knowledge_point("单调性", "高中数学", "函数")
            await planning.review_knowledge_points("函数", "高中数学", ["A", "B", "C"], min_points=1, max_points=3)

        self.assertEqual(captured[0], registry.render("study.kp.split.v1").content)
        self.assertEqual(captured[1], registry.render("lesson_plan.kp_facts.v1").content)
        self.assertEqual(captured[2], registry.render("study.kp.review.v1").content)

    async def test_latex_export_prompts_use_registry(self) -> None:
        from backend.generation.lesson_plan import export

        captured: list[str] = []

        async def fake_call_llm_text(*, messages, **_kwargs):  # type: ignore[no-untyped-def]
            captured.append(str(messages[0]["content"]))
            return "\\section{正文}"

        registry = create_default_prompt_registry()

        with patch("backend.generation.lesson_plan.export.call_llm_text", new=fake_call_llm_text):
            await export.convert_markdown_to_latex(markdown="# A", title="A", subject="高中数学")
            await export.refine_latex(latex="\\documentclass{article}\\begin{document}x\\end{document}", topic="A", subject="高中数学")

        self.assertEqual(captured[0], registry.render("lesson_plan.latex_convert.v1").content)
        self.assertEqual(captured[1], registry.render("lesson_plan.latex_repair.v1").content)


if __name__ == "__main__":
    unittest.main()
