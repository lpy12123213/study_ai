from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.agent.tools.analysis.content_review import ContentReviewToolsMixin
from backend.agent.tools.analysis.refine_draft import RefineDraftToolsMixin
from backend.agent.tools.analysis.self_critique import SelfCritiqueToolsMixin
from backend.agent.tools.analysis.source_synthesis import SourceSynthesisToolsMixin
from backend.agent.tools.generation.diagram_planning import DiagramPlanningToolsMixin
from backend.agent.tools.generation.latex_export_convert import LatexConvertMixin
from backend.agent.tools.generation.latex_export_refine import LatexRefineMixin
from backend.agent.tools.generation.paper_compose import PaperComposeToolsMixin
from backend.agent.tools.knowledge.knowledge_points import KnowledgePointsToolsMixin
from backend.agent.tools.knowledge.knowledge_type_detection import KnowledgeTypeDetectionToolsMixin
from backend.agent.tools.knowledge.question_bank import QuestionBankToolsMixin
from backend.agent.tools.knowledge.study_archive import StudyArchiveToolsMixin
from backend.agent.tools.knowledge.study_material_generation import StudyMaterialGenerationToolsMixin
from backend.agent.tools.search.deep_research import deep_research
from backend.agent.tools.search.web_search_knowledge import WebSearchKnowledgeToolsMixin
from backend.agent.types import ActionResults, CompressedContext, StepResult, UserProfile
from backend.llm.prompts import create_default_prompt_registry


class _DummyAgent(
    ContentReviewToolsMixin,
    DiagramPlanningToolsMixin,
    LatexConvertMixin,
    LatexRefineMixin,
    KnowledgePointsToolsMixin,
    KnowledgeTypeDetectionToolsMixin,
    PaperComposeToolsMixin,
    QuestionBankToolsMixin,
    RefineDraftToolsMixin,
    SelfCritiqueToolsMixin,
    SourceSynthesisToolsMixin,
    StudyArchiveToolsMixin,
    StudyMaterialGenerationToolsMixin,
    WebSearchKnowledgeToolsMixin,
):
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            reflector_model="reflector-test",
            summarizer_model="summarizer-test",
            planner_model="planner-test",
        )

    def _strict_llm(self, _ctx: CompressedContext, args: dict) -> bool:
        return bool(args.get("strict_llm"))

    async def _call_llm_text(self, **_kwargs):  # pragma: no cover - fallback tests should not hit LLM
        raise AssertionError("LLM should not be called in fallback unit tests")

    async def _call_llm_markdown_with_continuation(
        self,
        **_kwargs,
    ):  # pragma: no cover - fallback tests should not hit LLM
        raise AssertionError("LLM should not be called in fallback unit tests")

    def _extract_json_obj(self, _text: str) -> dict:
        raise AssertionError("JSON extraction should not be needed in fallback unit tests")


def _make_ctx(*, task: str = "导数", subject: str = "高中数学") -> CompressedContext:
    return CompressedContext(
        user_profile=UserProfile(user_id="u", preferences={"subject": subject}),
        system_instructions="",
        current_task=task,
    )


class TestStreamingArtifactCapture(unittest.TestCase):
    def test_capture_markdown_from_current_study_archive_tool_output(self) -> None:
        from backend.agent.streaming.events import maybe_capture_markdown_artifact

        results = ActionResults()
        step_result = StepResult(
            step_id="s1",
            tool="assemble_study_archive",
            success=True,
            output={"markdown": "# 导数\n\n导数刻画瞬时变化率。"},
        )

        maybe_capture_markdown_artifact(step_result=step_result, results=results)

        self.assertEqual(results.artifacts["markdown"], "# 导数\n\n导数刻画瞬时变化率。")

    def test_capture_export_artifact_refs_from_current_tool_output(self) -> None:
        from backend.agent.streaming.events import maybe_capture_markdown_artifact

        results = ActionResults()
        step_result = StepResult(
            step_id="s1",
            tool="export_study_markdown",
            success=True,
            output={"url": "/api/media/generated/study.md", "filename": "study.md"},
        )

        maybe_capture_markdown_artifact(step_result=step_result, results=results)

        self.assertEqual(results.artifacts["markdown_url"], "/api/media/generated/study.md")
        self.assertEqual(results.artifacts["markdown_filename"], "study.md")


class TestContentReviewMixin(unittest.IsolatedAsyncioTestCase):
    async def test_review_content_flags_missing_research_coverage(self) -> None:
        agent = _DummyAgent()
        ctx = _make_ctx()
        ctx.working_memory.update(
            {
                "markdown": "## 1. 导数\n只有一个简短定义。",
                "study_options": {"preset": "research"},
                "aggregated": {
                    "items": [
                        {
                            "knowledge_point": "导数",
                            "web_search": {
                                "results": [
                                    {"title": "导数简介", "snippet": "很短"},
                                ]
                            },
                            "web_pages": {"pages": []},
                        }
                    ]
                },
            }
        )

        with patch("backend.agent.tools.analysis.content_review.is_llm_configured", return_value=False):
            result = await agent._tool_review_content({}, ctx)

        self.assertFalse(result["passed"])
        self.assertEqual(result["source"], "heuristic")
        self.assertTrue(result["issues"])
        self.assertIn("导数", "\n".join(result["issues"]))

    async def test_review_and_revision_prompts_use_registry(self) -> None:
        class _Agent(_DummyAgent):
            def __init__(self) -> None:
                super().__init__()
                self.calls = []

            async def _call_llm_text(self, **kwargs):
                self.calls.append(kwargs)
                if kwargs.get("response_format"):
                    return json.dumps({"passed": True, "issues": [], "suggestions": []}, ensure_ascii=False)
                return "## 1、导数\n\n修订后内容。"

            def _extract_json_obj(self, text: str) -> dict:
                return json.loads(text)

        agent = _Agent()
        ctx = _make_ctx()
        ctx.working_memory["markdown"] = "## 1、导数\n\n导数刻画瞬时变化率。"

        with patch("backend.agent.tools.analysis.content_review.is_llm_configured", return_value=True):
            await agent._tool_review_content({}, ctx)
            await agent._tool_revise_markdown({"issues": ["补充适用条件"]}, ctx)

        registry = create_default_prompt_registry()
        self.assertEqual(agent.calls[0]["messages"][0]["content"], registry.render("agent.tool.content_review.v1").content)
        self.assertEqual(
            agent.calls[1]["messages"][0]["content"],
            registry.render("agent.tool.markdown_revision.v1").content,
        )


class TestSourceSynthesisMixin(unittest.IsolatedAsyncioTestCase):
    async def test_synthesize_sources_fallback_populates_brief_and_facts(self) -> None:
        agent = _DummyAgent()
        ctx = _make_ctx()
        ctx.working_memory["aggregated"] = {
            "items": [
                {
                    "knowledge_point": "导数",
                    "wikipedia": {"summary": "导数用于刻画函数的瞬时变化率。"},
                    "web_search": {"summary": "导数与切线斜率、单调性判断相关。", "results": []},
                }
            ]
        }

        with patch("backend.agent.tools.analysis.source_synthesis.is_llm_configured", return_value=False):
            result = await agent._tool_synthesize_sources({}, ctx)

        item = result["items"][0]
        brief = ctx.working_memory["source_briefs"]["导数"]
        self.assertEqual(item["knowledge_point"], "导数")
        self.assertEqual(item["source"], "heuristic")
        self.assertIn("导数用于刻画函数的瞬时变化率。", brief["definition"][0])
        self.assertEqual(ctx.working_memory["source_facts"]["导数"], [])

    async def test_synthesize_sources_prompt_uses_registry(self) -> None:
        class _Agent(_DummyAgent):
            def __init__(self) -> None:
                super().__init__()
                self.calls = []

            async def _call_llm_text(self, **kwargs):
                self.calls.append(kwargs)
                return json.dumps(
                    {
                        "brief": {
                            "definition": ["导数刻画函数在一点附近的瞬时变化率。"],
                            "core_ideas": ["几何上对应切线斜率。"],
                        },
                        "facts": [{"fact": "导数可用于研究单调性。", "confidence": 0.8, "source_ids": ["wiki"]}],
                    },
                    ensure_ascii=False,
                )

            def _extract_json_obj(self, text: str) -> dict:
                return json.loads(text)

        agent = _Agent()
        ctx = _make_ctx()
        ctx.working_memory["aggregated"] = {
            "items": [
                {
                    "knowledge_point": "导数",
                    "wikipedia": {"summary": "导数用于刻画函数的瞬时变化率。"},
                    "web_search": {"summary": "导数和切线斜率有关。", "results": []},
                }
            ]
        }

        with patch("backend.agent.tools.analysis.source_synthesis.is_llm_configured", return_value=True):
            await agent._tool_synthesize_sources({"knowledge_points": ["导数"]}, ctx)

        registry = create_default_prompt_registry()
        self.assertEqual(
            agent.calls[0]["messages"][0]["content"],
            registry.render("agent.tool.source_synthesis.v1").content,
        )


class TestDraftReviewMixin(unittest.IsolatedAsyncioTestCase):
    async def test_critique_and_refine_prompts_use_registry(self) -> None:
        class _Agent(_DummyAgent):
            def __init__(self) -> None:
                super().__init__()
                self.calls = []

            async def _call_llm_text(self, **kwargs):
                self.calls.append(kwargs)
                if kwargs.get("response_format"):
                    return json.dumps(
                        {
                            "score": 6.0,
                            "dimensions": {"accuracy": 7},
                            "issues": ["缺少适用条件"],
                            "revision_instructions": ["补充函数在目标点附近可导这一前提。"],
                        },
                        ensure_ascii=False,
                    )
                return "#### 动机与定义\n\n导数刻画瞬时变化率，使用前需确认函数在目标点附近可导。"

            def _extract_json_obj(self, text: str) -> dict:
                return json.loads(text)

        agent = _Agent()
        ctx = _make_ctx()
        ctx.working_memory["generate_study_material"] = {
            "sections": [
                {
                    "knowledge_point": "导数",
                    "explanation_markdown": "#### 动机与定义\n\n导数刻画瞬时变化率。",
                }
            ]
        }

        with patch("backend.agent.tools.analysis.self_critique.is_llm_configured", return_value=True):
            await agent._tool_critique_draft({"knowledge_points": ["导数"], "threshold": 7.0}, ctx)
        with patch("backend.agent.tools.analysis.refine_draft.is_llm_configured", return_value=True):
            await agent._tool_refine_draft({"knowledge_points": ["导数"], "threshold": 7.0}, ctx)

        registry = create_default_prompt_registry()
        self.assertEqual(
            agent.calls[0]["messages"][0]["content"],
            registry.render("agent.tool.draft_critique.v1").content,
        )
        self.assertEqual(
            agent.calls[1]["messages"][0]["content"],
            registry.render("agent.tool.draft_refine.v1").content,
        )


class TestWebSearchKnowledgeMixin(unittest.IsolatedAsyncioTestCase):
    async def test_web_search_subquestion_prompt_uses_registry(self) -> None:
        class _Agent(_DummyAgent):
            def __init__(self) -> None:
                super().__init__()
                self.calls = []

            async def _call_llm_text(self, **kwargs):
                self.calls.append(kwargs)
                return json.dumps({"sub_questions": ["导数定义是什么？", "导数有哪些适用条件？"]}, ensure_ascii=False)

            def _extract_json_obj(self, text: str) -> dict:
                return json.loads(text)

        async def metaso_ask(**_kwargs):
            return {"success": True, "answer": "定义：导数刻画瞬时变化率。", "results": []}

        agent = _Agent()
        ctx = _make_ctx()

        with patch("backend.agent.tools.search.web_search_knowledge_impl.is_llm_configured", return_value=True):
            with patch("backend.integrations.mcp.search.metaso.metaso_ask", metaso_ask):
                await agent._tool_web_search_knowledge(
                    {
                        "knowledge_points": ["导数"],
                        "search_mode": "metaso",
                        "metaso_mode": "ask",
                        "decompose": True,
                        "include_summary": True,
                    },
                    ctx,
                )

        registry = create_default_prompt_registry()
        self.assertEqual(
            agent.calls[0]["messages"][0]["content"],
            registry.render("search.web_subquestion.decompose.v1").content,
        )

    async def test_web_search_knowledge_defaults_to_tavily(self) -> None:
        agent = _DummyAgent()
        ctx = _make_ctx()

        tavily_search = AsyncMock(
            return_value={
                "success": True,
                "provider": "tavily",
                "query": "高中数学 导数",
                "results": [
                    {"title": "导数定义", "url": "https://example.com/tavily", "snippet": "导数表示瞬时变化率。"}
                ],
            }
        )

        args = {
            "knowledge_points": ["导数"],
            "decompose": False,
            "include_summary": True,
            "limit": 5,
        }

        with patch("backend.agent.tools.search.web_search_knowledge_impl.is_llm_configured", return_value=False):
            with patch("backend.integrations.mcp.search.tavily.TAVILY_API_KEY", "tvly-test"):
                with patch("backend.integrations.mcp.search.tavily.tavily_search", tavily_search):
                    result = await agent._tool_web_search_knowledge(args, ctx)

        item = result["items"][0]
        self.assertEqual(item["provider"], "tavily-search")
        self.assertEqual(item["results"][0]["url"], "https://example.com/tavily")
        tavily_search.assert_awaited_once()

    async def test_web_search_knowledge_reuses_working_memory_cache(self) -> None:
        agent = _DummyAgent()
        ctx = _make_ctx()

        metaso_ask = AsyncMock(
            return_value={
                "success": True,
                "answer": "导数可理解为函数在某一点的瞬时变化率。",
                "results": [
                    {"title": "定义", "url": "https://example.com/def", "snippet": "定义"},
                    {"title": "定义重复", "url": "https://example.com/def", "snippet": "重复"},
                ],
            }
        )

        args = {
            "knowledge_points": ["导数"],
            "search_mode": "metaso",
            "metaso_mode": "ask",
            "decompose": False,
            "include_summary": True,
            "limit": 5,
        }

        with patch("backend.agent.tools.search.web_search_knowledge_impl.is_llm_configured", return_value=False):
            with patch("backend.integrations.mcp.search.metaso.metaso_ask", metaso_ask):
                first = await agent._tool_web_search_knowledge(args, ctx)
                second = await agent._tool_web_search_knowledge(args, ctx)

        first_item = first["items"][0]
        second_item = second["items"][0]
        self.assertEqual(first_item["provider"], "metaso-ask")
        self.assertIn("瞬时变化率", first_item["summary"])
        self.assertEqual(len(first_item["results"]), 1)
        self.assertTrue(second_item["cache_hit"])
        self.assertEqual(metaso_ask.await_count, 1)


class TestDeepResearchPrompts(unittest.IsolatedAsyncioTestCase):
    async def test_deep_research_prompts_use_registry(self) -> None:
        calls = []

        async def call_llm_text(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return json.dumps({"queries": [{"query": "导数 定义", "research_goal": "查定义"}]}, ensure_ascii=False)
            return json.dumps(
                {"learnings": ["导数刻画瞬时变化率。"], "follow_up_questions": []},
                ensure_ascii=False,
            )

        def extract_json_obj(text: str) -> dict:
            return json.loads(text)

        async def search_func(_query: str, _limit: int) -> dict:
            return {"results": [{"title": "导数", "url": "https://example.com", "snippet": "导数是变化率。"}]}

        await deep_research(
            call_llm_text=call_llm_text,
            extract_json_obj=extract_json_obj,
            strict_llm=True,
            llm_model="model",
            knowledge_point="导数",
            subject="高中数学",
            seed_query="导数",
            search_func=search_func,
            breadth=1,
            depth=1,
            max_queries=3,
        )

        registry = create_default_prompt_registry()
        self.assertEqual(
            calls[0]["messages"][0]["content"],
            registry.render("search.deep_research.strategy.v1").content,
        )
        self.assertEqual(
            calls[1]["messages"][0]["content"],
            registry.render("search.deep_research.learning_extraction.v1").content,
        )


class TestKnowledgePromptMixins(unittest.IsolatedAsyncioTestCase):
    async def test_split_knowledge_points_uses_generic_domain_templates_without_llm(self) -> None:
        agent = _DummyAgent()
        ctx = _make_ctx(task="函数模型", subject="高中数学")

        with (
            patch("backend.agent.tools.knowledge.knowledge_points.is_llm_configured", return_value=False),
            patch(
                "backend.integrations.mcp.search.wikipedia.wikipedia_search",
                new=AsyncMock(return_value={"success": False}),
            ),
        ):
            result = await agent._tool_split_knowledge_points({"min_points": 4, "max_points": 6}, ctx)

        points = result["knowledge_points"]
        self.assertIn("函数模型 定义域和值域", points)
        self.assertIn("函数模型 图像与性质", points)
        self.assertGreaterEqual(len(points), 4)

    async def test_knowledge_point_prompts_use_registry(self) -> None:
        class _Agent(_DummyAgent):
            def __init__(self) -> None:
                super().__init__()
                self.calls = []

            async def _call_llm_text(self, **kwargs):
                self.calls.append(kwargs)
                return json.dumps({"knowledge_points": ["导数定义", "导数应用"], "note": "ok"}, ensure_ascii=False)

            def _extract_json_obj(self, text: str) -> dict:
                return json.loads(text)

        agent = _Agent()
        ctx = _make_ctx()

        with patch("backend.agent.tools.knowledge.knowledge_points.is_llm_configured", return_value=True):
            await agent._tool_split_knowledge_points({"min_points": 2, "max_points": 4}, ctx)
            await agent._tool_review_knowledge_points(
                {"knowledge_points": ["导数定义", "导数应用"], "min_points": 2, "max_points": 4},
                ctx,
            )

        registry = create_default_prompt_registry()
        self.assertEqual(agent.calls[0]["messages"][0]["content"], registry.render("study.kp.split.v1").content)
        self.assertEqual(agent.calls[1]["messages"][0]["content"], registry.render("study.kp.review.v1").content)

    async def test_knowledge_type_retrieve_and_diagram_prompts_use_registry(self) -> None:
        class _Agent(_DummyAgent):
            def __init__(self) -> None:
                super().__init__()
                self.calls = []

            async def _call_llm_text(self, **kwargs):
                self.calls.append(kwargs)
                if kwargs.get("max_tokens") == 900:
                    return json.dumps(
                        {
                            "knowledge_type": "concept",
                            "confidence": 0.8,
                            "focus": ["定义"],
                            "recommended_sections": ["动机与定义"],
                        },
                        ensure_ascii=False,
                    )
                if kwargs.get("max_tokens") == 2600:
                    return json.dumps(
                        {
                            "definition": "导数刻画瞬时变化率。",
                            "key_points": [],
                            "prerequisites": [],
                            "common_mistakes": [],
                            "methods": [],
                        },
                        ensure_ascii=False,
                    )
                return json.dumps({"diagrams": []}, ensure_ascii=False)

            def _extract_json_obj(self, text: str) -> dict:
                return json.loads(text)

        agent = _Agent()
        ctx = _make_ctx()
        ctx.working_memory["source_briefs"] = {"导数": {"definition": ["导数刻画变化率。"]}}

        with patch("backend.agent.tools.knowledge.knowledge_type_detection.is_llm_configured", return_value=True):
            await agent._tool_detect_knowledge_type({"knowledge_points": ["导数"]}, ctx)
        with patch("backend.agent.tools.knowledge.question_bank.is_llm_configured", return_value=True):
            await agent._tool_retrieve_knowledge({}, ctx)
        with patch("backend.agent.tools.generation.diagram_planning.is_llm_configured", return_value=True):
            await agent._tool_generate_diagrams({"knowledge_points": ["导数"], "max_diagrams": 1}, ctx)

        registry = create_default_prompt_registry()
        self.assertEqual(
            agent.calls[0]["messages"][0]["content"],
            registry.render("study.knowledge_type.detect.v1").content,
        )
        self.assertEqual(
            agent.calls[1]["messages"][0]["content"],
            registry.render("study.knowledge.retrieve.v1").content,
        )
        self.assertEqual(
            agent.calls[2]["messages"][0]["content"],
            registry.render("study.diagram.plan.v1").content,
        )


class TestLatexGenerationPrompts(unittest.IsolatedAsyncioTestCase):
    async def test_latex_convert_refine_and_paper_repair_prompts_use_registry(self) -> None:
        class _Agent(_DummyAgent):
            def __init__(self) -> None:
                super().__init__()
                self.response_calls = []
                self.text_calls = []

            async def _call_llm_response(self, **kwargs):
                self.response_calls.append(kwargs)
                if len(self.response_calls) == 1:
                    return {"content": "\\section{导数}\n导数刻画瞬时变化率。", "finish_reason": "stop", "usage": {}}
                return {
                    "content": "\\documentclass{article}\n\\begin{document}\n修订后\n\\end{document}",
                    "finish_reason": "stop",
                    "usage": {},
                }

            async def _call_llm_text(self, **kwargs):
                self.text_calls.append(kwargs)
                return json.dumps(
                    {"latex_tex": "\\documentclass{article}\n\\begin{document}\n修复后\n\\end{document}"},
                    ensure_ascii=False,
                )

            async def _emit_progress(self, **_kwargs) -> None:
                return None

            async def _emit_status(self, _content: str) -> None:
                return None

        agent = _Agent()
        ctx = _make_ctx()

        published = AsyncMock(
            return_value={"url": "/api/media/generated/a.tex", "filename": "a.tex", "sha256": "sha", "bytes": 10}
        )
        with patch("backend.agent.tools.generation.latex_export_convert.is_llm_configured", return_value=True):
            with patch("backend.agent.tools.generation.latex_export_convert.publish_generated_text", published):
                await agent._tool_convert_markdown_to_latex({"markdown": "## 1、导数\n\n导数刻画瞬时变化率。"}, ctx)

        with patch("backend.agent.tools.generation.latex_export_refine.is_llm_configured", return_value=True):
            with patch("backend.agent.tools.generation.latex_export_refine.publish_generated_text", published):
                await agent._tool_refine_latex(
                    {
                        "latex": "\\documentclass{article}\n\\begin{document}\n原文\n\\end{document}",
                        "compile_error": "Missing brace",
                    },
                    ctx,
                )

        ctx.working_memory["latex_tex"] = "\\documentclass{article}\n\\begin{document}\n坏\n\\end{document}"
        ctx.working_memory["latex_compile_log"] = "Missing brace"
        with patch("backend.agent.tools.generation.paper_compose.is_llm_configured", return_value=True):
            await agent._tool_repair_latex({}, ctx)

        registry = create_default_prompt_registry()
        self.assertEqual(
            agent.response_calls[0]["messages"][0]["content"],
            registry.render("study.latex.convert.v1").content,
        )
        self.assertEqual(
            agent.response_calls[1]["messages"][0]["content"],
            registry.render("study.latex.refine.v1").content,
        )
        self.assertEqual(
            agent.text_calls[0]["messages"][0]["content"],
            registry.render("paper_compose.latex_repair_json.v1").content,
        )

    def test_latex_continuation_helpers_use_registry(self) -> None:
        from backend.agent.tools.generation import latex_export_convert, latex_export_refine

        registry = create_default_prompt_registry()
        self.assertEqual(
            latex_export_convert._latex_convert_continuation_system_prompt(),
            registry.render("study.latex.convert_continuation.v1").content,
        )
        self.assertEqual(
            latex_export_refine._latex_refine_continuation_system_prompt(),
            registry.render("study.latex.refine_continuation.v1").content,
        )


class TestStudyMaterialGenerationMixin(unittest.IsolatedAsyncioTestCase):
    async def test_knowledge_point_writer_agent_revises_failed_draft(self) -> None:
        from backend.agent.tools.knowledge.study_material_generation import _KnowledgePointWriterAgent

        reviews = [
            {"passed": False, "issues": ["缺少适用条件"], "suggestions": ["补充成立前提"]},
            {"passed": True, "issues": [], "suggestions": []},
        ]
        calls = []

        async def write_draft() -> dict:
            calls.append("draft")
            return {
                "markdown": "初稿：只解释了定义。",
                "finish_reason": "stop",
                "usage": {"total_tokens": 10},
                "continuations": 0,
            }

        async def review_draft(markdown: str) -> dict:
            calls.append(f"review:{markdown[:2]}")
            return reviews.pop(0)

        async def revise_draft(markdown: str, review: dict) -> str:
            calls.append(f"revise:{review['issues'][0]}")
            return markdown + "\n\n修订：补充适用条件。"

        agent = _KnowledgePointWriterAgent(
            knowledge_point="导数",
            plan={"sections": [{"title": "动机与定义"}]},
            write_draft=write_draft,
            review_draft=review_draft,
            revise_draft=revise_draft,
            max_revision_rounds=2,
        )

        result = await agent.run()

        self.assertIn("补充适用条件", result.markdown)
        self.assertEqual(result.revisions, 1)
        self.assertEqual(result.review["passed"], True)
        self.assertEqual([x["action"] for x in result.actions], ["plan", "draft", "review", "revise", "review"])
        self.assertEqual(calls, ["draft", "review:初稿", "revise:缺少适用条件", "review:初稿"])

    async def test_generate_study_material_falls_back_to_synthesized_items(self) -> None:
        agent = _DummyAgent()
        ctx = _make_ctx()
        ctx.working_memory.update(
            {
                "study_options": {"preset": "quick"},
                "synthesize_sources": {
                    "topic": "导数",
                    "subject": "高中数学",
                    "items": [{"knowledge_point": "导数"}],
                },
                "source_briefs": {
                    "导数": {
                        "definition": ["导数用于刻画函数在某一点的瞬时变化率。"],
                        "core_ideas": ["导数与切线斜率、变化快慢有关。"],
                        "key_properties": [],
                        "conditions_and_boundaries": [],
                        "common_misconceptions": [],
                        "applications": ["可用于判断函数单调性。"],
                        "derivation_or_proof_sketch": [],
                        "notation_and_terms": [],
                    }
                },
                "source_facts": {"导数": []},
            }
        )

        with patch("backend.agent.tools.knowledge.study_material_generation.is_llm_configured", return_value=False):
            result = await agent._tool_generate_study_material({}, ctx)

        self.assertEqual(result["topic"], "导数")
        self.assertEqual(len(result["sections"]), 1)
        section = result["sections"][0]
        self.assertEqual(section["knowledge_point"], "导数")
        self.assertTrue(section["explanation_markdown"].strip())
        self.assertIn("####", section["explanation_markdown"])

    async def test_generate_study_material_uses_writer_agent_review_and_revision(self) -> None:
        class _AgenticDummyAgent(_DummyAgent):
            def __init__(self) -> None:
                super().__init__()
                self.review_calls = 0
                self.markdown_messages = []
                self.text_messages = []

            async def _call_llm_markdown_with_continuation(self, **kwargs):
                self.markdown_messages.append(kwargs.get("messages"))
                return {
                    "content": "初稿：只说明导数是瞬时变化率。",
                    "finish_reason": "stop",
                    "usage": {"total_tokens": 12},
                    "continuations": 0,
                }

            async def _call_llm_text(self, **kwargs):
                self.text_messages.append(kwargs.get("messages"))
                if kwargs.get("response_format"):
                    self.review_calls += 1
                    if self.review_calls == 1:
                        return json.dumps(
                            {
                                "passed": False,
                                "issues": ["缺少适用条件"],
                                "suggestions": ["说明函数在点附近需要可导。"],
                            },
                            ensure_ascii=False,
                        )
                    return json.dumps({"passed": True, "issues": [], "suggestions": []}, ensure_ascii=False)
                return "修订稿：导数刻画瞬时变化率；使用前要确认函数在目标点附近可导。"

            def _extract_json_obj(self, text: str) -> dict:
                return json.loads(text)

            async def _emit_status(self, _content: str) -> None:
                return None

        agent = _AgenticDummyAgent()
        ctx = _make_ctx()
        ctx.working_memory.update(
            {
                "study_options": {"preset": "quick"},
                "aggregate_knowledge": {
                    "topic": "导数",
                    "subject": "高中数学",
                    "items": [
                        {
                            "knowledge_point": "导数",
                            "web_search": {
                                "results": [
                                    {"title": "导数定义", "url": "https://example.com/d", "snippet": "瞬时变化率"}
                                ]
                            },
                        }
                    ],
                },
                "outlines": {
                    "导数": {
                        "sections": [
                            {
                                "title": "动机与定义",
                                "hints": ["解释瞬时变化率"],
                                "verify": ["说明适用条件"],
                            }
                        ]
                    }
                },
            }
        )

        with patch("backend.agent.tools.knowledge.study_material_generation.is_llm_configured", return_value=True):
            result = await agent._tool_generate_study_material(
                {
                    "topic": "导数",
                    "subject": "高中数学",
                    "knowledge_points": ["导数"],
                    "max_points": 1,
                },
                ctx,
            )

        section = result["sections"][0]
        self.assertEqual(section["explanation_source"], "writer_agent")
        self.assertIn("修订稿", section["explanation_markdown"])
        self.assertEqual(section["writer_agent"]["revisions"], 1)
        self.assertEqual(section["writer_agent"]["review"]["passed"], True)
        self.assertIn("revise", [x["action"] for x in section["writer_agent"]["actions"]])

        registry = create_default_prompt_registry()
        self.assertEqual(
            agent.markdown_messages[0][0]["content"],
            registry.render("study.material.section_writer.v1").content,
        )
        self.assertEqual(
            agent.text_messages[0][0]["content"],
            registry.render("study.material.section_reviewer.v1").content,
        )
        self.assertEqual(
            agent.text_messages[1][0]["content"],
            registry.render("study.material.section_revision.v1").content,
        )
        self.assertEqual(
            agent.text_messages[2][0]["content"],
            registry.render("study.material.section_reviewer.v1").content,
        )

    def test_study_material_generation_prompts_use_registry(self) -> None:
        from backend.agent.tools.knowledge import study_material_generation as smg

        registry = create_default_prompt_registry()
        self.assertEqual(smg._outline_system_prompt(), registry.render("study.material.outline.v1").content)
        self.assertEqual(
            smg._section_writer_system_prompt(),
            registry.render("study.material.section_writer.v1").content,
        )
        self.assertEqual(
            smg._section_reviewer_system_prompt(),
            registry.render("study.material.section_reviewer.v1").content,
        )
        self.assertEqual(
            smg._section_revision_system_prompt(),
            registry.render("study.material.section_revision.v1").content,
        )

    async def test_section_writer_payload_includes_grade_band_and_curriculum_context(self) -> None:
        class _CurriculumAgent(_DummyAgent):
            def __init__(self) -> None:
                super().__init__()
                self.markdown_messages = []
                self.text_messages = []

            async def _call_llm_markdown_with_continuation(self, **kwargs):
                self.markdown_messages.append(kwargs.get("messages"))
                return {"content": "函数模型要匹配高中阶段的定义域与值域要求。", "finish_reason": "stop"}

            async def _call_llm_text(self, **kwargs):
                self.text_messages.append(kwargs.get("messages"))
                return json.dumps({"passed": True, "issues": [], "suggestions": []}, ensure_ascii=False)

            def _extract_json_obj(self, text: str) -> dict:
                return json.loads(text)

        agent = _CurriculumAgent()
        ctx = _make_ctx(task="函数模型", subject="高中数学")
        ctx.working_memory.update(
            {
                "study_options": {
                    "preset": "quick",
                    "grade_band": "senior",
                    "curriculum_context": {
                        "question_requirements": ["围绕高中函数建模，不引入大学分析工具"],
                        "knowledge_scope": {"out_of_scope": ["极限的严格定义"]},
                        "prerequisites": ["一次函数", "二次函数"],
                    },
                },
                "aggregate_knowledge": {
                    "topic": "函数模型",
                    "subject": "高中数学",
                    "items": [{"knowledge_point": "函数建模"}],
                },
                "outlines": {"函数建模": {"sections": [{"title": "模型边界", "hints": [], "verify": []}]}},
            }
        )

        with patch("backend.agent.tools.knowledge.study_material_generation.is_llm_configured", return_value=True):
            await agent._tool_generate_study_material(
                {"topic": "函数模型", "subject": "高中数学", "knowledge_points": ["函数建模"], "max_points": 1},
                ctx,
            )

        payload = json.loads(agent.markdown_messages[0][1]["content"])
        self.assertEqual(payload["grade_band"], "senior")
        self.assertIn("curriculum_context", payload)
        self.assertIn("围绕高中函数建模", "\n".join(payload["curriculum_context"]["question_requirements"]))
        self.assertIn("极限的严格定义", "\n".join(payload["curriculum_context"]["knowledge_scope"]["out_of_scope"]))
        self.assertTrue(any("curriculum_context" in item for item in payload["instructions"]))

    async def test_assemble_study_archive_treats_writer_agent_as_model_output(self) -> None:
        agent = _DummyAgent()
        ctx = _make_ctx()
        ctx.working_memory["study_options"] = {"with_diagrams": False}
        ctx.working_memory["generate_study_material"] = {
            "topic": "导数",
            "subject": "高中数学",
            "sections": [
                {
                    "knowledge_point": "导数",
                    "explanation_markdown": "#### 动机与定义\n\n导数刻画瞬时变化率。",
                    "explanation_source": "writer_agent",
                }
            ],
        }

        await agent._tool_assemble_study_archive({"topic": "导数", "with_diagrams": False}, ctx)

        markdown = str(ctx.working_memory.get("markdown") or "")
        self.assertIn("导数刻画瞬时变化率", markdown)
        self.assertNotIn("未成功使用模型生成", markdown)


if __name__ == "__main__":
    unittest.main()
