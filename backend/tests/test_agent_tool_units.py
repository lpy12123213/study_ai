from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.agent.tools.analysis.content_review import ContentReviewToolsMixin
from backend.agent.tools.analysis.source_synthesis import SourceSynthesisToolsMixin
from backend.agent.tools.search.web_search_knowledge import WebSearchKnowledgeToolsMixin
from backend.agent.types import CompressedContext, UserProfile


class _DummyAgent(ContentReviewToolsMixin, SourceSynthesisToolsMixin, WebSearchKnowledgeToolsMixin):
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

        with patch("backend.agent.tools.search.web_search_knowledge.is_llm_configured", return_value=False):
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


if __name__ == "__main__":
    unittest.main()
