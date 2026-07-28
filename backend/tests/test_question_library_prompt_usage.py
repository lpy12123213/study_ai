from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend.llm.prompts import create_default_prompt_registry


class QuestionLibraryPromptUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_brainstorm_prompt_includes_registry_base_prompt(self) -> None:
        from backend.generation.question_library import brainstorm

        captured = {}

        async def fake_chat_json_with_reasoning(*, messages, **_kwargs):  # type: ignore[no-untyped-def]
            captured["system"] = str(messages[0]["content"])
            captured["payload"] = json.loads(str(messages[1]["content"]))
            return (
                '{"seeds":[{"concept":"A","angle":"B","seed_tag":"C","skill_hint":"D",'
                '"reasoning_hint":"E","mother_question_demand":"从给出的部分和关系发现隐藏对称",'
                '"topic_binding":"对称性进入部分和配对条件；不变量进入结论判定"}]}'
            )

        with patch("backend.generation.question_library.brainstorm.is_llm_configured", return_value=True):
            with patch("backend.generation.question_library.brainstorm._chat_json_with_reasoning", new=fake_chat_json_with_reasoning):
                seeds = await brainstorm.brainstorm_creative_seeds(
                    {
                        "subject": "高中数学",
                        "topic": "导数",
                        "requested_topic": "导数\n第二行要求：必须改变边界或表征，不能只换数字。",
                        "intuition_practice": {
                            "practice_goal": "solution_appreciation",
                            "intuition_kinds": ["prediction", "solution_comparison"],
                            "packet_size": 4,
                        },
                    },
                    seed_count=6,
                )

        self.assertEqual(len(seeds), 1)
        self.assertIn(
            create_default_prompt_registry().render("question.brainstorm.v1").content,
            captured["system"],
        )
        self.assertIn("Low entry means curriculum-accessible prerequisites", captured["system"])
        self.assertIn("Keep decisive_cue in the private design atom", captured["system"])
        self.assertIn("changing at least one relationship", captured["system"])
        self.assertIn("two genuinely different representations", captured["system"])
        self.assertIn("mother_question_demand", captured["system"])
        self.assertIn("Every retained subpart must contribute evidence", captured["system"])
        self.assertIn("every substantive clause in the requested topic", captured["system"])
        self.assertIn("solution_appreciation cannot rescue a routine base task", captured["system"])
        self.assertIn("ask the learner to find them", captured["system"])
        self.assertEqual(
            captured["payload"]["topic"],
            "导数\n第二行要求：必须改变边界或表征，不能只换数字。",
        )
        self.assertEqual(seeds[0]["mother_question_demand"], "从给出的部分和关系发现隐藏对称")
        self.assertIn("不变量", seeds[0]["topic_binding"])

    def test_draft_prompt_requires_intuition_bearing_mother_question(self) -> None:
        from backend.generation.question_library.draft_realization import build_generation_messages

        messages = build_generation_messages(
            subject="高中数学",
            topic="等差数列的对称性",
            difficulty="中等",
            question_type="解答题",
            study_markdown="",
            count=1,
            spec={
                "brainstorm_mother_question_demand": "从部分和关系发现隐藏对称并判断极值位置",
                "brainstorm_topic_binding": "对称性和不变量都进入母题的配对关系",
                "intuition_practice": {
                    "practice_goal": "solution_appreciation",
                    "intuition_kinds": ["prediction", "invariant", "solution_comparison"],
                    "packet_size": 4,
                    "feedback_mode": "guided",
                },
            },
            source_pack={"subject": "高中数学", "topic": "等差数列的对称性"},
        )

        system = str(messages[0]["content"])
        payload = json.loads(str(messages[1]["content"]))
        self.assertIn("if intuition_packet is deleted", system)
        self.assertIn("find the parameters/general term", system)
        self.assertIn("every subpart must preserve or deepen", system)
        self.assertIn("Delete intuition_packet mentally", system)
        self.assertIn("every substantive requested-topic clause", system)
        self.assertIn("given \\(a_{n}\\), find the extremum", system)
        self.assertIn("Method comparison is an analysis lens, not a source of difficulty", system)
        self.assertIn("the learner to find or construct two genuinely different routes", system)
        self.assertEqual(
            payload["spec"]["brainstorm_mother_question_demand"],
            "从部分和关系发现隐藏对称并判断极值位置",
        )
        self.assertEqual(
            payload["spec"]["brainstorm_topic_binding"],
            "对称性和不变量都进入母题的配对关系",
        )

    async def test_judging_prompts_include_registry_base_prompts(self) -> None:
        from backend.generation.question_library import judging

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

        with patch("backend.generation.question_library.judging.is_llm_configured", return_value=True):
            with patch("backend.generation.question_library.judging._chat_json_with_reasoning", new=fake_chat_json_with_reasoning):
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
