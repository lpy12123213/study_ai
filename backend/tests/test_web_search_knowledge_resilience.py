"""Resilience tests for the web_search_knowledge tool layer.

Covers:
- per-invocation decompose cache (one LLM call per knowledge point across provider fallbacks)
- task-scoped LLM health flag (permanent misconfig -> template split, no more LLM calls)
- task-scoped provider health cache (quota/auth failure -> provider skipped afterwards)
- distinct "search_providers_unavailable" error when every provider is permanently down
"""

from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import backend.agent.tools.search.web_search_knowledge_impl as impl
from backend.agent.tools.search.web_search_knowledge import WebSearchKnowledgeToolsMixin
from backend.agent.types import CompressedContext, UserProfile

# Neutralize deployment env so tests are deterministic regardless of the local .env.
_ENV_PATCH = patch.dict(
    os.environ,
    {
        "STUDY_MATERIALS_SEARCH_MODE": "",
        "STUDY_MATERIALS_PRESET": "",
        "STUDY_MATERIALS_DISABLE_METASO": "",
    },
)

_PERMANENT_400 = (
    "llm_request_failed status=400 model=deprecated-model provider=fireworks "
    "msg=supported API model names are [accounts/fireworks/models/deepseek-v3p1]"
)
_PERMANENT_LLM_401 = "llm_request_failed status=401 model=deepseek-test provider=fireworks msg=Unauthorized"
_TRANSIENT_TIMEOUT = "llm_request_failed model=deepseek-test err=ReadTimeout"


class _Agent(WebSearchKnowledgeToolsMixin):
    def __init__(self, *, llm_error: Exception | None = None, llm_payload: dict | None = None) -> None:
        self.config = SimpleNamespace(
            reflector_model="reflector-test",
            summarizer_model="summarizer-test",
            planner_model="planner-test",
        )
        self.llm_calls: list[dict] = []
        self._llm_error = llm_error
        self._llm_payload = llm_payload

    def _strict_llm(self, _ctx: CompressedContext, args: dict) -> bool:
        return bool(args.get("strict_llm"))

    async def _call_llm_text(self, **kwargs):
        self.llm_calls.append(kwargs)
        if self._llm_error is not None:
            raise self._llm_error
        return json.dumps(self._llm_payload or {}, ensure_ascii=False)

    def _extract_json_obj(self, text: str) -> dict:
        try:
            obj = json.loads(text)
        except (TypeError, ValueError):
            return {}
        return obj if isinstance(obj, dict) else {}


def _make_ctx(*, task: str = "高中数学 复习", subject: str = "高中数学") -> CompressedContext:
    return CompressedContext(
        user_profile=UserProfile(user_id="u", preferences={"subject": subject}),
        system_instructions="",
        current_task=task,
    )


def _sub_questions_payload(*questions: str) -> dict:
    return {"sub_questions": list(questions)}


def _tavily_error(error: str) -> dict:
    return {"success": False, "provider": "tavily", "query": "q", "error": error, "results": []}


def _exa_error(error: str) -> dict:
    return {"success": False, "provider": "exa", "query": "q", "error": error, "results": []}


def _search_ok(provider: str, url: str) -> dict:
    return {
        "success": True,
        "provider": provider,
        "query": "q",
        "results": [{"title": "导数定义", "url": url, "snippet": "导数表示瞬时变化率。"}],
    }


def _health(ctx: CompressedContext) -> dict:
    store = ctx.working_memory.get("_web_search_health")
    return store if isinstance(store, dict) else {}


class TestWebSearchKnowledgeResilience(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        impl._TASK_HEALTH_FALLBACK.clear()
        _ENV_PATCH.start()
        self.addCleanup(_ENV_PATCH.stop)

    def _patches(self, *, tavily_search, exa_search, llm_configured: bool = True):
        return [
            patch(
                "backend.agent.tools.search.web_search_knowledge_impl.is_llm_configured",
                return_value=llm_configured,
            ),
            patch("backend.integrations.mcp.search.tavily.TAVILY_API_KEY", "tvly-test"),
            patch("backend.integrations.mcp.search.tavily.tavily_search", tavily_search),
            patch("backend.integrations.mcp.search.exa.EXA_API_KEY", "exa-test"),
            patch("backend.integrations.mcp.search.exa.exa_search", exa_search),
        ]

    async def test_decompose_llm_called_once_across_provider_fallbacks(self) -> None:
        agent = _Agent(
            llm_payload=_sub_questions_payload("导数的定义是什么？", "导数的几何意义是什么？", "导数有哪些常见误区？")
        )
        ctx = _make_ctx()
        tavily_search = AsyncMock(return_value=_tavily_error("Tavily API error: 500"))
        exa_search = AsyncMock(return_value=_search_ok("exa", "https://example.com/exa"))

        args = {"knowledge_points": ["导数"], "decompose": True, "disable_metaso": True, "limit": 5}
        for p in self._patches(tavily_search=tavily_search, exa_search=exa_search):
            p.start()
            self.addCleanup(p.stop)

        result = await agent._tool_web_search_knowledge(args, ctx)

        item = result["items"][0]
        self.assertEqual(item["provider"], "exa-search+decompose")
        self.assertTrue(item["results"])
        # Tavily failed transiently, then Exa succeeded; the decompose LLM ran once.
        self.assertEqual(len(agent.llm_calls), 1)
        self.assertEqual(tavily_search.await_count, 3)
        self.assertEqual(exa_search.await_count, 3)
        # Transient 500 must not mark the provider down.
        self.assertFalse(_health(ctx).get("providers_down"))

    async def test_permanent_400_trips_llm_flag_for_subsequent_points(self) -> None:
        agent = _Agent(llm_error=RuntimeError(_PERMANENT_400))
        ctx = _make_ctx()
        tavily_search = AsyncMock(return_value=_tavily_error("Tavily API error: 500"))
        exa_search = AsyncMock(return_value=_search_ok("exa", "https://example.com/exa"))

        for p in self._patches(tavily_search=tavily_search, exa_search=exa_search):
            p.start()
            self.addCleanup(p.stop)

        first = await agent._tool_web_search_knowledge(
            {"knowledge_points": ["导数"], "decompose": True, "disable_metaso": True}, ctx
        )
        second = await agent._tool_web_search_knowledge(
            {"knowledge_points": ["极限"], "decompose": True, "disable_metaso": True}, ctx
        )

        # The permanent 400 tripped the task-scoped flag on the first point; the second
        # point went straight to the deterministic template split with no LLM call.
        self.assertEqual(len(agent.llm_calls), 1)
        self.assertTrue(_health(ctx).get("llm_decompose_down"))
        for res in (first, second):
            item = res["items"][0]
            self.assertEqual(item["provider"], "exa-search+decompose")
            self.assertTrue(item["results"])
            self.assertTrue(any("定义" in q for q in item["sub_questions"]))

    async def test_transient_timeout_does_not_trip_llm_flag(self) -> None:
        agent = _Agent(llm_error=RuntimeError(_TRANSIENT_TIMEOUT))
        ctx = _make_ctx()
        tavily_search = AsyncMock(return_value=_search_ok("tavily", "https://example.com/tavily"))
        exa_search = AsyncMock(return_value=_search_ok("exa", "https://example.com/exa"))

        for p in self._patches(tavily_search=tavily_search, exa_search=exa_search):
            p.start()
            self.addCleanup(p.stop)

        first = await agent._tool_web_search_knowledge(
            {"knowledge_points": ["导数"], "decompose": True, "disable_metaso": True}, ctx
        )
        second = await agent._tool_web_search_knowledge(
            {"knowledge_points": ["极限"], "decompose": True, "disable_metaso": True}, ctx
        )

        # Timeout is transient: the flag stays clear and the next point retries the LLM.
        self.assertEqual(len(agent.llm_calls), 2)
        self.assertFalse(_health(ctx).get("llm_decompose_down"))
        for res in (first, second):
            self.assertEqual(res["items"][0]["provider"], "tavily-search+decompose")
        exa_search.assert_not_awaited()

    async def test_tavily_quota_failure_skips_tavily_for_next_point(self) -> None:
        agent = _Agent()
        ctx = _make_ctx()
        tavily_search = AsyncMock(return_value=_tavily_error("Tavily API error: 432"))
        exa_search = AsyncMock(return_value=_search_ok("exa", "https://example.com/exa"))

        for p in self._patches(tavily_search=tavily_search, exa_search=exa_search, llm_configured=False):
            p.start()
            self.addCleanup(p.stop)

        first = await agent._tool_web_search_knowledge(
            {"knowledge_points": ["导数"], "decompose": False, "disable_metaso": True}, ctx
        )
        second = await agent._tool_web_search_knowledge(
            {"knowledge_points": ["极限"], "decompose": False, "disable_metaso": True}, ctx
        )

        # KP-1 paid one Tavily 432; KP-2 skipped Tavily entirely and went straight to Exa.
        self.assertEqual(tavily_search.await_count, 1)
        self.assertEqual(exa_search.await_count, 2)
        self.assertIn("tavily", (_health(ctx).get("providers_down") or {}))
        self.assertEqual(first["items"][0]["provider"], "exa-search")
        self.assertEqual(second["items"][0]["provider"], "exa-search")

    async def test_all_providers_permanent_down_yields_distinct_error(self) -> None:
        agent = _Agent()
        ctx = _make_ctx()
        tavily_search = AsyncMock(return_value=_tavily_error("Tavily API error: 432"))
        exa_search = AsyncMock(return_value=_exa_error("Exa API error: 401"))
        bigmodel_search = AsyncMock(return_value={"success": False, "error": "boom", "results": []})

        for p in self._patches(tavily_search=tavily_search, exa_search=exa_search, llm_configured=False):
            p.start()
            self.addCleanup(p.stop)
        with patch(
            "backend.integrations.mcp.search.bigmodel.web_search_with_bigmodel_mcp", bigmodel_search
        ):
            result = await agent._tool_web_search_knowledge(
                {"knowledge_points": ["导数"], "decompose": False, "disable_metaso": True}, ctx
            )

        item = result["items"][0]
        self.assertEqual(item["error"], "search_providers_unavailable")
        self.assertEqual(item["provider"], "none")
        self.assertEqual(item["results"], [])
        downs = _health(ctx).get("providers_down") or {}
        self.assertIn("tavily", downs)
        self.assertIn("exa", downs)

    async def test_happy_path_unchanged(self) -> None:
        agent = _Agent(llm_payload=_sub_questions_payload("导数的定义是什么？", "导数的几何意义是什么？"))
        ctx = _make_ctx()
        tavily_search = AsyncMock(return_value=_search_ok("tavily", "https://example.com/tavily"))
        exa_search = AsyncMock(return_value=_search_ok("exa", "https://example.com/exa"))

        for p in self._patches(tavily_search=tavily_search, exa_search=exa_search):
            p.start()
            self.addCleanup(p.stop)

        result = await agent._tool_web_search_knowledge(
            {"knowledge_points": ["导数"], "decompose": True, "include_summary": True, "limit": 5}, ctx
        )

        item = result["items"][0]
        self.assertEqual(item["provider"], "tavily-search+decompose")
        self.assertEqual(item["results"][0]["url"], "https://example.com/tavily")
        self.assertEqual(item["sub_questions"], ["导数的定义是什么？", "导数的几何意义是什么？"])
        self.assertEqual(len(agent.llm_calls), 1)
        self.assertEqual(tavily_search.await_count, 2)
        exa_search.assert_not_awaited()
        self.assertFalse(_health(ctx))

    async def test_strict_llm_401_does_not_mark_providers_down(self) -> None:
        # Regression: in strict mode the decompose LLM error (401) propagates through the
        # provider-level except; the healthy providers (never even called) must not be
        # banned for the rest of the task.
        agent = _Agent(llm_error=RuntimeError(_PERMANENT_LLM_401))
        ctx = _make_ctx()
        tavily_search = AsyncMock(return_value=_search_ok("tavily", "https://example.com/tavily"))
        exa_search = AsyncMock(return_value=_search_ok("exa", "https://example.com/exa"))

        for p in self._patches(tavily_search=tavily_search, exa_search=exa_search):
            p.start()
            self.addCleanup(p.stop)

        result = await agent._tool_web_search_knowledge(
            {"knowledge_points": ["导数"], "decompose": True, "disable_metaso": True, "strict_llm": True}, ctx
        )

        self.assertFalse(_health(ctx).get("providers_down"))
        # The permanent LLM 401 still trips the LLM health flag, so the Exa fallback
        # used the deterministic template split instead of the dead LLM.
        self.assertTrue(_health(ctx).get("llm_decompose_down"))
        tavily_search.assert_not_awaited()
        item = result["items"][0]
        self.assertEqual(item["provider"], "exa-search+decompose")
        self.assertTrue(item["results"])

    async def test_subquestion_text_does_not_trip_provider_quota_match(self) -> None:
        # Regression: the knowledge point itself contains "401 Unauthorized", so every
        # sub-question does too. Transient 500s must not be misread as permanent
        # quota/auth failures just because the composite "sub_q: err" string matches.
        agent = _Agent()
        ctx = _make_ctx()
        tavily_search = AsyncMock(return_value=_tavily_error("Tavily API error: 500"))
        exa_search = AsyncMock(return_value=_exa_error("Exa API error: 500"))
        bigmodel_search = AsyncMock(return_value={"success": False, "error": "boom", "results": []})

        for p in self._patches(tavily_search=tavily_search, exa_search=exa_search, llm_configured=False):
            p.start()
            self.addCleanup(p.stop)

        with patch(
            "backend.integrations.mcp.search.bigmodel.web_search_with_bigmodel_mcp", bigmodel_search
        ):
            result = await agent._tool_web_search_knowledge(
                {"knowledge_points": ["401 Unauthorized 认证流程"], "decompose": True, "disable_metaso": True},
                ctx,
            )

        self.assertFalse(_health(ctx).get("providers_down"))
        item = result["items"][0]
        self.assertEqual(item["provider"], "none")
        self.assertNotEqual(item.get("error"), "search_providers_unavailable")

    async def test_deepresearch_subquestion_text_does_not_mark_provider_down(self) -> None:
        # Same pollution guard for the deep-research engine, which builds its own
        # "query: err" composites from LLM/template-generated queries.
        agent = _Agent()
        ctx = _make_ctx()
        tavily_search = AsyncMock(return_value=_tavily_error("Tavily API error: 500"))
        exa_search = AsyncMock(return_value=_search_ok("exa", "https://example.com/exa"))

        for p in self._patches(tavily_search=tavily_search, exa_search=exa_search, llm_configured=False):
            p.start()
            self.addCleanup(p.stop)

        result = await agent._tool_web_search_knowledge(
            {
                "knowledge_points": ["401 Unauthorized 认证流程"],
                "search_mode": "deepresearch",
                "disable_metaso": True,
                "deep_depth": 1,
                "deep_breadth": 2,
                "max_queries": 3,
            },
            ctx,
        )

        self.assertFalse(_health(ctx).get("providers_down"))
        self.assertEqual(result["items"][0]["provider"], "exa-deepresearch")

    async def test_deepresearch_quota_error_marks_provider_down(self) -> None:
        # Positive control: a genuine provider quota error inside deep research must
        # still mark the provider down (the raw error list keeps the real signal).
        agent = _Agent()
        ctx = _make_ctx()
        tavily_search = AsyncMock(return_value=_tavily_error("Tavily API error: 432"))
        exa_search = AsyncMock(return_value=_search_ok("exa", "https://example.com/exa"))

        for p in self._patches(tavily_search=tavily_search, exa_search=exa_search, llm_configured=False):
            p.start()
            self.addCleanup(p.stop)

        result = await agent._tool_web_search_knowledge(
            {
                "knowledge_points": ["导数"],
                "search_mode": "deepresearch",
                "disable_metaso": True,
                "deep_depth": 1,
                "deep_breadth": 2,
                "max_queries": 3,
            },
            ctx,
        )

        self.assertIn("tavily", (_health(ctx).get("providers_down") or {}))
        self.assertEqual(result["items"][0]["provider"], "exa-deepresearch")

    async def test_metaso_auth_check_ignores_subquestion_text(self) -> None:
        # Regression: Metaso's all-auth-errors check must run on raw provider errors,
        # not on "sub_q: err" composites (the topic here contains "invalid api key").
        agent = _Agent()
        ctx = _make_ctx()
        metaso_ask = AsyncMock(return_value={"success": False, "error": "Metaso API error: 500", "results": []})

        for p in self._patches(tavily_search=AsyncMock(), exa_search=AsyncMock(), llm_configured=False):
            p.start()
            self.addCleanup(p.stop)

        with patch("backend.integrations.mcp.search.metaso.metaso_ask", metaso_ask):
            await agent._tool_web_search_knowledge(
                {
                    "knowledge_points": ["invalid api key 报错的排查流程"],
                    "decompose": True,
                    "search_mode": "metaso",
                },
                ctx,
            )

        self.assertFalse(_health(ctx).get("providers_down"))

    async def test_metaso_real_auth_error_marks_provider_down(self) -> None:
        # Positive control: every sub-question failing with a real 401 still bans Metaso.
        agent = _Agent()
        ctx = _make_ctx()
        metaso_ask = AsyncMock(return_value={"success": False, "error": "Metaso API error: 401", "results": []})

        for p in self._patches(tavily_search=AsyncMock(), exa_search=AsyncMock(), llm_configured=False):
            p.start()
            self.addCleanup(p.stop)

        with patch("backend.integrations.mcp.search.metaso.metaso_ask", metaso_ask):
            await agent._tool_web_search_knowledge(
                {"knowledge_points": ["导数"], "decompose": True, "search_mode": "metaso"},
                ctx,
            )

        self.assertIn("metaso", (_health(ctx).get("providers_down") or {}))


if __name__ == "__main__":
    unittest.main()
