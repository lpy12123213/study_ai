from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.generation.agentic.prompts import create_default_prompt_registry


class QuestionLibraryPromptUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_brainstorm_prompt_includes_registry_base_prompt(self) -> None:
        from backend.question_library import brainstorm

        captured = {}

        async def fake_chat_json_with_reasoning(*, messages, **_kwargs):  # type: ignore[no-untyped-def]
            captured["system"] = str(messages[0]["content"])
            return '{"seeds":[{"concept":"A","angle":"B","seed_tag":"C","skill_hint":"D","reasoning_hint":"E"}]}'

        with patch("backend.question_library.brainstorm.is_llm_configured", return_value=True):
            with patch("backend.question_library.brainstorm._chat_json_with_reasoning", new=fake_chat_json_with_reasoning):
                seeds = await brainstorm.brainstorm_creative_seeds(
                    {"subject": "高中数学", "topic": "导数"},
                    seed_count=6,
                )

        self.assertEqual(len(seeds), 1)
        self.assertIn(
            create_default_prompt_registry().render("question.brainstorm.v1").content,
            captured["system"],
        )

    async def test_judging_prompts_include_registry_base_prompts(self) -> None:
        from backend.question_library import judging

        captured: list[str] = []
        returns = [
            '{"match":true,"final_answer":"2","issues":[],"summary":"ok"}',
            '{"ambiguous":false,"issues":[],"summary":"ok"}',
            '{"pass":true,"verdict":"好题","overall_score":80,"dimensions":[],"issues":[],"summary":"ok"}',
            '{"stem":"1+1=?","answer":"2","analysis":"ok"}',
        ]

        async def fake_chat_json_with_reasoning(*, messages, **_kwargs):  # type: ignore[no-untyped-def]
            captured.append(str(messages[0]["content"]))
            return returns.pop(0)

        registry = create_default_prompt_registry()

        with patch("backend.question_library.judging.is_llm_configured", return_value=True):
            with patch("backend.question_library.judging._chat_json_with_reasoning", new=fake_chat_json_with_reasoning):
                await judging.solve_draft("1+1=?", {"subject": "高中数学", "proposed_answer": "2"})
                await judging.check_ambiguity({"stem": "1+1=?", "answer": "2"})
                await judging.judge_draft(
                    {"stem": "1+1=?", "answer": "2", "analysis": "ok"},
                    {"subject": "高中数学", "difficulty": "中等"},
                )
                await judging.refine_draft(
                    {"stem": "1+1=?", "answer": "2", "analysis": "bad"},
                    {"issues": ["解析太短"]},
                )

        self.assertIn(registry.render("question.solve.independent.v1").content, captured[0])
        self.assertIn(registry.render("question.judge.ambiguity.v1").content, captured[1])
        self.assertIn(registry.render("question.judge.quality.v1").content, captured[2])
        self.assertIn(registry.render("question.repair.minimal.v1").content, captured[3])


if __name__ == "__main__":
    unittest.main()
