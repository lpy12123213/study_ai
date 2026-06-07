from __future__ import annotations

import unittest

from backend.generation.agentic.prompt_contracts import (
    JsonOutputContract,
    MarkdownOutputContract,
)
from backend.generation.agentic.prompts import (
    JSON_ONLY_GUARDRAIL,
    NO_MARKDOWN_FENCE_GUARDRAIL,
    ORIGINAL_REWRITE_GUARDRAIL,
    PromptRegistry,
    PromptTemplate,
    create_default_prompt_registry,
)


class AgenticPromptRegistryTests(unittest.TestCase):
    def test_default_registry_contains_target_prompt_ids_for_current_domains(self) -> None:
        registry = create_default_prompt_registry()
        prompt_ids = {prompt.id for prompt in registry.list_templates()}
        expected = {
            "agent.react.controller.v1",
            "agent.core.system_instructions.v1",
            "agent.planner.study_materials.v1",
            "agent.planner.execution_plan.v1",
            "agent.reflector.study_materials.v1",
            "agent.exporter.study_materials.v1",
            "agent.markdown.continuation.v1",
            "agent.subagent.summary.v1",
            "agent.subagent.summary_plain.v1",
            "agent.context.compress.v1",
            "agent.executor.markdown_continuation.v1",
            "agent.tool.content_review.v1",
            "agent.tool.markdown_revision.v1",
            "agent.tool.source_synthesis.v1",
            "agent.tool.draft_critique.v1",
            "agent.tool.draft_refine.v1",
            "study.kp.split.v1",
            "study.kp.review.v1",
            "study.knowledge_type.detect.v1",
            "study.knowledge.retrieve.v1",
            "study.knowledge.retrieve.user.v1",
            "study.diagram.plan.v1",
            "study.sources.synthesize.v1",
            "study.material.outline.v1",
            "study.material.writer.v1",
            "study.material.section_writer.v1",
            "study.material.section_reviewer.v1",
            "study.material.section_revision.v1",
            "study.material.document_review.v1",
            "study.material.document_revision.v1",
            "search.query.decompose.v1",
            "search.web_subquestion.decompose.v1",
            "search.deep_research.strategy.v1",
            "search.deep_research.learning_extraction.v1",
            "search.source_fact.normalize.v1",
            "question.brainstorm.v1",
            "question.draft.realize.v1",
            "question.draft.retry_json.v1",
            "question.curriculum_context.v1",
            "question.solve.independent.v1",
            "question.judge.ambiguity.v1",
            "question.judge.quality.v1",
            "question.repair.minimal.v1",
            "question.section.regenerate.v1",
            "question.evaluate.external.v1",
            "question.score.thinking_depth_batch.v1",
            "question.score.single_quality.v1",
            "question.media_import.extract.v1",
            "question.source_pack.extract.v1",
            "question.reference.analyze.v1",
            "question.diagram.revise.v1",
            "question.diagram.verify.v1",
            "question.diagram.need.v1",
            "question.diagram.spec.v1",
            "paper_compose.planner.v1",
            "paper_compose.searcher.v1",
            "paper_compose.author.v1",
            "paper_compose.composer.v1",
            "paper_compose.compiler.v1",
            "paper_compose.repairer.v1",
            "paper_compose.reviewer.v1",
            "paper_compose.structure_planner.v1",
            "paper_compose.question_match_reviewer.v1",
            "paper_compose.latex_repair_json.v1",
            "paper_compose.analysis_comment.user.v1",
            "deepthink.generator.v1",
            "deepthink.evaluator.v1",
            "deepthink.synthesizer.v1",
            "lesson_plan.writer.v1",
            "lesson_plan.kp_facts.v1",
            "lesson_plan.activity_planner.v1",
            "lesson_plan.latex_convert.v1",
            "lesson_plan.latex_repair.v1",
            "study.latex.convert.v1",
            "study.latex.convert_continuation.v1",
            "study.latex.refine.v1",
            "study.latex.refine_continuation.v1",
            "chat.paper_compose.system.v1",
            "knowledge_video.manim_package.v1",
            "knowledge_video.manim_code.v1",
            "exam.subjective.grade.v1",
            "essay.evaluate.system.v1",
            "mcp.knowledge_facts.v1",
            "mcp.study_section.v1",
            "mcp.solve_stepwise.v1",
            "mcp.review_study_material.v1",
            "mcp.context_summarize.v1",
            "mcp.question_reviewer.v1",
            "mcp.paper_reviewer.v1",
            "mcp.paper_reviewer.user.v1",
            "mcp.retrieve_knowledge.user.v1",
            "mcp.bigmodel.web_search_prompt.v1",
            "mcp.bigmodel.summarize_url_prompt.v1",
            "mcp.bigmodel.mcp_web_search_prompt.v1",
            "mcp.sub_ai_selector.user.v1",
        }

        self.assertEqual(expected - prompt_ids, set())

    def test_rejects_duplicate_prompt_ids(self) -> None:
        registry = PromptRegistry()
        template = PromptTemplate(
            id="agent.test.v1",
            role="system",
            version="v1",
            input_keys=("topic",),
            output_contract=JsonOutputContract(),
            template="请围绕 {topic} 输出 JSON。\n" + JSON_ONLY_GUARDRAIL + "\n" + NO_MARKDOWN_FENCE_GUARDRAIL,
        )

        registry.register(template)

        with self.assertRaises(ValueError):
            registry.register(template)

    def test_render_requires_declared_inputs(self) -> None:
        registry = PromptRegistry()
        registry.register(
            PromptTemplate(
                id="agent.render.v1",
                role="user",
                version="v1",
                input_keys=("topic", "subject"),
                output_contract=JsonOutputContract(),
                template="学科：{subject}\n主题：{topic}\n" + JSON_ONLY_GUARDRAIL,
            )
        )

        with self.assertRaises(KeyError):
            registry.render("agent.render.v1", topic="函数")

        rendered = registry.render("agent.render.v1", topic="函数", subject="高中数学")
        self.assertEqual(rendered.prompt_id, "agent.render.v1")
        self.assertIn("高中数学", rendered.content)
        self.assertIn("函数", rendered.content)

    def test_json_prompts_include_json_only_guardrails(self) -> None:
        registry = create_default_prompt_registry()
        json_prompts = [
            prompt
            for prompt in registry.list_templates()
            if isinstance(prompt.output_contract, JsonOutputContract)
        ]

        self.assertGreaterEqual(len(json_prompts), 1)
        for prompt in json_prompts:
            text = prompt.render({key: "x" for key in prompt.input_keys}).content
            issues = prompt.output_contract.validate_prompt_text(text)
            self.assertEqual(issues, [], msg=f"{prompt.id}: {issues}")

    def test_educational_markdown_prompts_include_source_and_rewrite_guardrails(self) -> None:
        registry = create_default_prompt_registry()
        markdown_prompts = [
            prompt
            for prompt in registry.list_templates()
            if isinstance(prompt.output_contract, MarkdownOutputContract)
            and prompt.output_contract.educational_writing
        ]

        self.assertGreaterEqual(len(markdown_prompts), 1)
        for prompt in markdown_prompts:
            text = prompt.render({key: "x" for key in prompt.input_keys}).content
            issues = prompt.output_contract.validate_prompt_text(text)
            self.assertEqual(issues, [], msg=f"{prompt.id}: {issues}")
            self.assertIn(ORIGINAL_REWRITE_GUARDRAIL, text)


if __name__ == "__main__":
    unittest.main()
