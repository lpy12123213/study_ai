from __future__ import annotations

import unittest

from backend.agent.react.prompts import build_react_messages
from backend.agent.types import CompressedContext, UserProfile
from backend.generation.agentic.prompt_contracts import (
    JsonOutputContract,
    MarkdownOutputContract,
)
from backend.llm.prompts import create_default_prompt_registry


class PromptContractTests(unittest.TestCase):
    def test_json_contract_flags_markdown_leakage_risk(self) -> None:
        contract = JsonOutputContract()

        issues = contract.validate_prompt_text("请输出 JSON。")

        self.assertIn("missing_no_markdown_constraint", issues)
        self.assertIn("missing_no_code_fence_constraint", issues)

    def test_json_contract_accepts_strict_json_prompt(self) -> None:
        contract = JsonOutputContract()

        issues = contract.validate_prompt_text(
            "必须输出严格 JSON object，不要输出 Markdown，不要输出代码块，不要额外解释。"
        )

        self.assertEqual(issues, [])

    def test_educational_markdown_contract_requires_rewrite_and_source_guardrails(self) -> None:
        contract = MarkdownOutputContract(educational_writing=True)

        issues = contract.validate_prompt_text("请输出 Markdown。")

        self.assertIn("missing_original_rewrite_constraint", issues)
        self.assertIn("missing_no_url_constraint", issues)
        self.assertIn("missing_source_grounding_constraint", issues)

    def test_react_messages_use_registered_controller_prompt(self) -> None:
        ctx = CompressedContext(
            user_profile=UserProfile(user_id="u", preferences={"subject": "高中数学"}),
            system_instructions="",
            current_task="函数",
        )
        messages = build_react_messages(
            ctx=ctx,
            topic="函数",
            subject="高中数学",
            tools=[{"name": "web_search_knowledge", "description": "搜索"}],
            scratchpad="",
            iteration=0,
            max_iterations=3,
            budget_remaining=5,
        )

        registered = create_default_prompt_registry().render("agent.react.controller.v1").content

        self.assertEqual(messages[0]["content"], registered)
        self.assertIn("strict JSON object", messages[0]["content"])
        self.assertEqual(messages[0].get("cache_control"), {"type": "ephemeral"})
        self.assertEqual(messages[1].get("cache_control"), {"type": "ephemeral"})
        self.assertTrue(any("web_search_knowledge" in str(m.get("content") or "") for m in messages))

    def test_deepthink_prompts_render_from_registry(self) -> None:
        from backend.generation.deepthink.prompts import (
            get_evaluator_system_prompt,
            get_generator_system_prompt,
            get_synthesizer_system_prompt,
        )

        registry = create_default_prompt_registry()

        self.assertEqual(
            get_generator_system_prompt("高中数学"),
            registry.render("deepthink.generator.v1", subject="高中数学").content,
        )
        self.assertEqual(
            get_evaluator_system_prompt("高中数学"),
            registry.render("deepthink.evaluator.v1", subject="高中数学").content,
        )
        self.assertEqual(
            get_synthesizer_system_prompt("高中数学"),
            registry.render("deepthink.synthesizer.v1", subject="高中数学").content,
        )

    def test_lesson_plan_writer_prompt_renders_from_registry(self) -> None:
        from backend.generation.lesson_plan.prompts import get_system_prompt

        registered = create_default_prompt_registry().render("lesson_plan.writer.v1").content

        self.assertEqual(get_system_prompt(), registered)
        self.assertIn("strict JSON object", registered)
        self.assertIn("Do not copy any source text verbatim", registered)

    def test_paper_compose_prompt_renders_from_registry(self) -> None:
        from backend.workspace.chat.prompts import PLAN_TAG_CLOSE, PLAN_TAG_OPEN, get_system_prompt

        registered = create_default_prompt_registry().render(
            "chat.paper_compose.system.v1",
            subject="高中数学",
            subject_topic="函数",
            plan_open=PLAN_TAG_OPEN,
            plan_close=PLAN_TAG_CLOSE,
        ).content

        self.assertEqual(get_system_prompt("高中数学"), registered)
        self.assertIn(PLAN_TAG_OPEN, registered)
        self.assertIn("Do not output full question stems", registered)


if __name__ == "__main__":
    unittest.main()
