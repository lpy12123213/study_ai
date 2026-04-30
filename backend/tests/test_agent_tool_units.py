from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.agent.tools.analysis.content_review import ContentReviewToolsMixin
from backend.agent.tools.analysis.source_synthesis import SourceSynthesisToolsMixin
from backend.agent.tools.knowledge.study_archive import StudyArchiveToolsMixin
from backend.agent.tools.knowledge.study_material_generation import StudyMaterialGenerationToolsMixin
from backend.agent.tools.search.web_search_knowledge import WebSearchKnowledgeToolsMixin
from backend.agent.types import CompressedContext, UserProfile


class _DummyAgent(
    ContentReviewToolsMixin,
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


class TestWebSearchKnowledgeMixin(unittest.IsolatedAsyncioTestCase):
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
            with patch("backend.mcp.search.metaso.metaso_ask", metaso_ask):
                first = await agent._tool_web_search_knowledge(args, ctx)
                second = await agent._tool_web_search_knowledge(args, ctx)

        first_item = first["items"][0]
        second_item = second["items"][0]
        self.assertEqual(first_item["provider"], "metaso-ask")
        self.assertIn("瞬时变化率", first_item["summary"])
        self.assertEqual(len(first_item["results"]), 1)
        self.assertTrue(second_item["cache_hit"])
        self.assertEqual(metaso_ask.await_count, 1)


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

            async def _call_llm_markdown_with_continuation(self, **_kwargs):
                return {
                    "content": "初稿：只说明导数是瞬时变化率。",
                    "finish_reason": "stop",
                    "usage": {"total_tokens": 12},
                    "continuations": 0,
                }

            async def _call_llm_text(self, **kwargs):
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
