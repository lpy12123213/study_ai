import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from backend.core import settings as settings_module
from backend.core.settings import Settings, model_role_binding
from backend.generation.question_library.evolution import (
    GENERATOR_ROLE,
    abstract_payload_for_muse,
    build_policy_population,
    policy_fitness,
)
from backend.generation.question_library.gen_llm import _bounded_role_max_tokens
from backend.llm import client as llm_client
from backend.llm.providers import CHAT_COMPLETIONS_PROTOCOL, RESPONSES_PROTOCOL, resolve_protocol
from backend.llm.retry import _request_timeout_s


class OpenCodeGoProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_unbounded_request_omits_token_cap_and_http_timeout(self) -> None:
        captured: dict = {}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001,ARG002
                pass

            async def aclose(self) -> None:
                return None

            async def post(self, url, headers=None, json=None, timeout="unset"):  # noqa: ANN001,ANN201
                captured.update({"url": url, "payload": dict(json or {}), "timeout": timeout})
                return httpx.Response(
                    200,
                    json={
                        "id": "resp_unbounded",
                        "status": "completed",
                        "output": [
                            {"type": "message", "content": [{"type": "output_text", "text": '{"ok":true}'}]}
                        ],
                        "usage": {"input_tokens": 2, "output_tokens": 2, "total_tokens": 4},
                    },
                    request=httpx.Request("POST", url),
                )

        with patch.object(llm_client.httpx, "AsyncClient", FakeAsyncClient):
            result = await llm_client.chat_completion(
                messages=[{"role": "user", "content": "Return JSON"}],
                model="muse-spark-1.2-contributor",
                temperature=0.5,
                max_tokens=0,
                timeout_s=0,
                stream=False,
                raise_on_fail=True,
                retries=1,
                provider="opencode_go",
                base_url="https://opencode.ai/zen/go/v1",
                api_key="test-key",
                moonshot_key="",
                moonshot_base_url="",
            )

        self.assertEqual(result.content, '{"ok":true}')
        self.assertNotIn("max_output_tokens", captured["payload"])
        self.assertNotIn("max_tokens", captured["payload"])
        self.assertIsNone(captured["timeout"])

    async def test_muse_uses_responses_endpoint_and_parses_output_usage(self) -> None:
        captured: dict = {}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001,ARG002
                pass

            async def aclose(self) -> None:
                return None

            async def post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001,ANN201
                captured.update({"url": url, "headers": headers, "payload": dict(json or {}), "timeout": timeout})
                return httpx.Response(
                    200,
                    json={
                        "id": "resp_1",
                        "status": "completed",
                        "output": [
                            {"type": "message", "content": [{"type": "output_text", "text": '{"ok":true}'}]}
                        ],
                        "usage": {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
                    },
                    request=httpx.Request("POST", url),
                )

        with patch.object(llm_client.httpx, "AsyncClient", FakeAsyncClient):
            result = await llm_client.chat_completion(
                messages=[{"role": "user", "content": "Return JSON"}],
                model="muse-spark-1.2-contributor",
                temperature=0.5,
                max_tokens=80,
                response_format={"type": "json_object"},
                reasoning={"effort": "high"},
                tools=[{"type": "function", "function": {"name": "unused", "parameters": {"type": "object"}}}],
                stream=False,
                raise_on_fail=True,
                retries=1,
                provider="opencode_go",
                base_url="https://opencode.ai/zen/go/v1",
                api_key="test-key",
                moonshot_key="",
                moonshot_base_url="",
            )

        self.assertEqual(captured["url"], "https://opencode.ai/zen/go/v1/responses")
        self.assertEqual(captured["payload"]["model"], "muse-spark-1.2-contributor")
        self.assertIn("input", captured["payload"])
        self.assertNotIn("messages", captured["payload"])
        self.assertIn("max_output_tokens", captured["payload"])
        self.assertNotIn("max_tokens", captured["payload"])
        self.assertNotIn("tools", captured["payload"])
        self.assertNotIn("reasoning", captured["payload"])
        self.assertEqual(json.loads(result.content), {"ok": True})
        self.assertEqual(result.usage["output_tokens"], 4)

    async def test_muse_streaming_parses_responses_deltas(self) -> None:
        captured: dict = {}

        class FakeStreamResponse:
            status_code = 200
            headers = {}

            async def __aenter__(self):  # noqa: ANN201
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001,ANN201
                return False

            async def aiter_lines(self):  # noqa: ANN201
                yield 'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":"}'
                yield 'data: {"type":"response.output_text.delta","delta":"true}"}'
                yield 'data: {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":8,"output_tokens":3}}}'

            def raise_for_status(self) -> None:
                return None

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001,ARG002
                pass

            async def aclose(self) -> None:
                return None

            def stream(self, method, url, headers=None, json=None, timeout=None):  # noqa: ANN001,ANN201
                captured.update({"method": method, "url": url, "payload": dict(json or {}), "timeout": timeout})
                return FakeStreamResponse()

        chunks: list[str] = []

        async def on_delta(value: str) -> None:
            chunks.append(value)

        with patch.object(llm_client.httpx, "AsyncClient", FakeAsyncClient):
            result = await llm_client.chat_completion(
                messages=[{"role": "user", "content": "Return JSON"}],
                model="muse-spark-1.2-contributor",
                temperature=0.5,
                max_tokens=80,
                stream=True,
                on_content_delta=on_delta,
                raise_on_fail=True,
                retries=1,
                provider="opencode_go",
                base_url="https://opencode.ai/zen/go/v1",
                api_key="test-key",
                moonshot_key="",
                moonshot_base_url="",
            )

        self.assertEqual(captured["url"], "https://opencode.ai/zen/go/v1/responses")
        self.assertTrue(captured["payload"]["stream"])
        self.assertEqual(result.content, '{"ok":true}')
        self.assertEqual(chunks, ['{"ok":', "true}"])
        self.assertEqual(result.usage["output_tokens"], 3)

    async def test_incomplete_responses_result_is_an_explicit_error(self) -> None:
        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001,ARG002
                pass

            async def aclose(self) -> None:
                return None

            async def post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001,ANN201,ARG002
                return httpx.Response(
                    200,
                    json={
                        "id": "resp_incomplete",
                        "status": "incomplete",
                        "incomplete_details": {"reason": "max_output_tokens"},
                        "output": [],
                        "usage": {"input_tokens": 8, "output_tokens": 80},
                    },
                    request=httpx.Request("POST", url),
                )

        with patch.object(llm_client.httpx, "AsyncClient", FakeAsyncClient):
            with self.assertRaisesRegex(RuntimeError, "max_output_tokens"):
                await llm_client.chat_completion(
                    messages=[{"role": "user", "content": "Return JSON"}],
                    model="muse-spark-1.2-contributor",
                    temperature=0.3,
                    max_tokens=80,
                    stream=False,
                    raise_on_fail=True,
                    retries=1,
                    provider="opencode_go",
                    base_url="https://opencode.ai/zen/go/v1",
                    api_key="test-key",
                    moonshot_key="",
                    moonshot_base_url="",
                )

    async def test_deepseek_uses_chat_completions_without_model_prefix_rewrite(self) -> None:
        captured: dict = {}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001,ARG002
                pass

            async def aclose(self) -> None:
                return None

            async def post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001,ANN201
                captured.update({"url": url, "payload": dict(json or {})})
                return httpx.Response(
                    200,
                    json={
                        "choices": [{"message": {"content": '{"pass":true}'}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                    },
                    request=httpx.Request("POST", url),
                )

        with patch.object(llm_client.httpx, "AsyncClient", FakeAsyncClient):
            result = await llm_client.chat_completion(
                messages=[{"role": "user", "content": "Review"}],
                model="deepseek-v4-flash",
                temperature=0.1,
                max_tokens=40,
                stream=False,
                raise_on_fail=True,
                retries=1,
                provider="opencode_go",
                base_url="https://opencode.ai/zen/go/v1",
                api_key="test-key",
                moonshot_key="",
                moonshot_base_url="",
            )

        self.assertEqual(captured["url"], "https://opencode.ai/zen/go/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "deepseek-v4-flash")
        self.assertEqual(json.loads(result.content), {"pass": True})

    async def test_quota_error_fails_without_cross_provider_fallback(self) -> None:
        urls: list[str] = []

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001,ARG002
                pass

            async def aclose(self) -> None:
                return None

            async def post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001,ANN201,ARG002
                urls.append(url)
                return httpx.Response(
                    402,
                    json={"error": {"message": "quota exhausted"}},
                    request=httpx.Request("POST", url),
                )

        with patch.object(llm_client.httpx, "AsyncClient", FakeAsyncClient):
            with self.assertRaisesRegex(RuntimeError, "provider=opencode_go"):
                await llm_client.chat_completion(
                    messages=[{"role": "user", "content": "Review"}],
                    model="deepseek-v4-flash",
                    temperature=0.1,
                    max_tokens=40,
                    stream=False,
                    raise_on_fail=True,
                    retries=1,
                    provider="opencode_go",
                    base_url="https://opencode.ai/zen/go/v1",
                    api_key="test-key",
                    moonshot_key="",
                    moonshot_base_url="",
                )

        self.assertEqual(urls, ["https://opencode.ai/zen/go/v1/chat/completions"])

    async def test_rate_limit_error_stays_on_opencode_go_endpoint(self) -> None:
        urls: list[str] = []

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001,ARG002
                pass

            async def aclose(self) -> None:
                return None

            async def post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001,ANN201,ARG002
                urls.append(url)
                return httpx.Response(
                    429,
                    json={"error": {"message": "rate limited"}},
                    request=httpx.Request("POST", url),
                )

        with patch.object(llm_client.httpx, "AsyncClient", FakeAsyncClient):
            with self.assertRaisesRegex(RuntimeError, "status=429"):
                await llm_client.chat_completion(
                    messages=[{"role": "user", "content": "Review"}],
                    model="deepseek-v4-flash",
                    temperature=0.1,
                    max_tokens=40,
                    stream=False,
                    raise_on_fail=True,
                    retries=1,
                    provider="opencode_go",
                    base_url="https://opencode.ai/zen/go/v1",
                    api_key="test-key",
                    moonshot_key="",
                    moonshot_base_url="",
                )

        self.assertEqual(urls, ["https://opencode.ai/zen/go/v1/chat/completions"])

    def test_protocol_selection_is_model_specific(self) -> None:
        self.assertEqual(
            resolve_protocol(provider="opencode_go", model="muse-spark-1.2-contributor"),
            RESPONSES_PROTOCOL,
        )
        self.assertEqual(
            resolve_protocol(provider="opencode_go", model="deepseek-v4-flash"),
            CHAT_COMPLETIONS_PROTOCOL,
        )


class OpenCodeGoConfigurationTests(unittest.TestCase):
    def test_question_roles_have_per_call_output_token_caps(self) -> None:
        self.assertEqual(_bounded_role_max_tokens(GENERATOR_ROLE, 0), 6_000)
        self.assertEqual(_bounded_role_max_tokens(GENERATOR_ROLE, 12_000), 6_000)
        self.assertEqual(_bounded_role_max_tokens("question_library_supervisor", 0), 4_000)
        self.assertEqual(_bounded_role_max_tokens("question_library_supervisor", 9_000), 4_000)
        self.assertEqual(_bounded_role_max_tokens(GENERATOR_ROLE, 12_000, unbounded=True), 0)
        self.assertIsNone(_request_timeout_s(0))
        self.assertEqual(_request_timeout_s(9_000), 600.0)

    def test_unbounded_trace_skips_only_output_token_budgets(self) -> None:
        from backend.generation.question_library.evolution import create_trace

        trace = create_trace(
            generation_strategy="adaptive_evolution",
            supervision_mode="tiered_consensus",
            policy_mode="champion",
            seed="unbounded",
            unbounded_live_test=True,
        )
        trace.reserve_call(GENERATOR_ROLE)
        trace.record_call(
            role=GENERATOR_ROLE,
            model="muse-spark-1.2-contributor",
            protocol="responses",
            usage={"output_tokens": 999_999},
            elapsed_s=1.0,
        )

        self.assertEqual(trace.stop_reason, "completed")
        self.assertTrue(trace.summary()["unbounded_live_test"])
        self.assertEqual(trace.muse_call_limit, 60)
        self.assertEqual(trace.deepseek_call_limit, 40)

    def test_generation_request_defaults_to_adaptive_tiered_champion(self) -> None:
        from backend.api.question_library_schemas import QuestionLibraryGenerateRequest

        request = QuestionLibraryGenerateRequest(subject="高中数学", topic="函数边界")
        self.assertEqual(request.generation_strategy, "adaptive_evolution")
        self.assertEqual(request.supervision_mode, "tiered_consensus")
        self.assertEqual(request.policy_mode, "champion")

    def test_specialist_roles_are_strict_and_have_no_generic_fallback(self) -> None:
        payload = {
            "active_provider": "other",
            "pinned": True,
            "providers": {
                "other": {"base_url": "https://other.example/v1", "api_key": "other-key"},
                "opencode_go": {"base_url": "https://opencode.ai/zen/go/v1", "api_key": "go-key"},
            },
            "routes": {
                "chat": "other",
                "lesson_plan": "other",
                "review": "other",
                "question_library_generator": "opencode_go",
                "question_library_supervisor": "opencode_go",
                "question_library_arbiter": "opencode_go",
            },
            "models": {
                "main": "other-model",
                "lesson_plan": "other-model",
                "review": "other-model",
                "question_library_generator": "muse-spark-1.2-contributor",
                "question_library_supervisor": "deepseek-v4-flash",
                "question_library_arbiter": "deepseek-v4-flash",
            },
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.dict(os.environ, {"MODEL_CONFIG_PATH": str(path)}, clear=False):
                configured = Settings.from_env()
        with patch.object(settings_module, "settings", configured):
            binding = model_role_binding(GENERATOR_ROLE, required_provider="opencode_go")
            self.assertEqual(binding.provider, "opencode_go")
            self.assertEqual(binding.model, "muse-spark-1.2-contributor")
            configured.model_routes.pop(GENERATOR_ROLE, None) if isinstance(configured.model_routes, dict) else None
            with self.assertRaisesRegex(RuntimeError, "model_role_route_missing"):
                model_role_binding(GENERATOR_ROLE, required_provider="opencode_go")

    def test_muse_payload_redaction_and_policy_constraints(self) -> None:
        redacted = abstract_payload_for_muse(
            {
                "topic": "函数边界",
                "study_markdown": "private notes",
                "reference_questions": [{"stem": "real exam"}],
                "reference_examples": [{"stem": "real exam"}],
                "constraints": {"in_scope": ["导数"]},
            }
        )
        self.assertNotIn("study_markdown", redacted)
        self.assertNotIn("reference_questions", redacted)
        self.assertNotIn("reference_examples", redacted)
        self.assertEqual(redacted["constraints"]["in_scope"], ["导数"])

        policies = build_policy_population(
            generation_strategy="adaptive_evolution",
            policy_mode="shadow_compare",
            seed="case-1",
        )
        self.assertEqual(len(policies), 4)
        for policy in policies:
            self.assertGreaterEqual(policy.temperature, 0.3)
            self.assertLessEqual(policy.temperature, 0.8)
            self.assertGreaterEqual(policy.spec_population, 6)
            self.assertLessEqual(policy.spec_population, 12)
            self.assertIn(policy.branch_factor, {1, 2, 3})
            self.assertGreaterEqual(policy.mutation_rate, 0.1)
            self.assertLessEqual(policy.mutation_rate, 0.35)
            self.assertIn(policy.drafts_per_spec, {1, 2})
            self.assertIn(policy.repair_rounds, {0, 1})
            self.assertGreaterEqual(policy.confidence_threshold, 0.7)
            self.assertLessEqual(policy.confidence_threshold, 0.9)

        self.assertEqual(
            policy_fitness(
                passed=True,
                confidence=0.99,
                evidence_count=0,
                usage={"output_tokens": 10},
                latency_s=0.1,
                arbitrated=False,
            ),
            0.0,
        )

    def test_failed_trace_records_provider_stop_reason(self) -> None:
        from backend.generation.question_library.evolution import create_trace

        trace = create_trace(
            generation_strategy="adaptive_evolution",
            supervision_mode="tiered_consensus",
            policy_mode="champion",
            seed="failure",
        )
        trace.reserve_call("question_library_supervisor")
        trace.record_failure(role="question_library_supervisor", error="upstream 500", fatal=True)
        summary = trace.summary()
        self.assertEqual(summary["failed_calls"], 1)
        self.assertEqual(summary["stop_reason"], "provider_error")


class OpenCodeGoFailureSemanticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_enrichment_failure_returns_empty_without_provider_fallback(self) -> None:
        from backend.generation.question_library import gen_llm
        from backend.generation.question_library.evolution import bind_trace, create_trace, reset_trace

        trace = create_trace(
            generation_strategy="adaptive_evolution",
            supervision_mode="tiered_consensus",
            policy_mode="champion",
            seed="optional-failure",
        )
        token = bind_trace(trace)
        binding = SimpleNamespace(
            provider="opencode_go",
            model="deepseek-v4-flash",
            base_url="https://opencode.ai/zen/go/v1",
            api_key="test-key",
        )
        try:
            with (
                patch.object(gen_llm, "model_role_binding", return_value=binding),
                patch.object(gen_llm, "chat_completion", new=AsyncMock(side_effect=RuntimeError("disconnect"))),
                patch.object(gen_llm, "chat_completion_text", new=AsyncMock(side_effect=RuntimeError("disconnect"))),
            ):
                text = await gen_llm._chat_json_with_reasoning(
                    messages=[{"role": "user", "content": "optional context"}],
                    model="ignored",
                    temperature=0.2,
                    max_tokens=0,
                    req_id_prefix="ql_curriculum",
                    retries=1,
                    raise_on_fail=False,
                    stage_id="curriculum_context",
                    stage_label="课标对齐",
                    stream_reasoning=False,
                    on_reasoning_event=None,
                )
        finally:
            reset_trace(token)

        self.assertEqual(text, "")
        self.assertEqual(trace.summary()["failed_calls"], 2)
        self.assertEqual(trace.stop_reason, "completed")
        self.assertTrue(all(item["model"] == "deepseek-v4-flash" for item in trace.calls))


class TieredSupervisionTests(unittest.IsolatedAsyncioTestCase):
    def test_repair_feedback_keeps_only_standardized_issue_codes(self) -> None:
        from backend.generation.question_library.judging import standardized_issue_codes

        self.assertEqual(
            standardized_issue_codes(
                ["answer_incorrect", "完整监督推理不应传给生成器", "ambiguous:details", "answer_incorrect"]
            ),
            ["answer_incorrect"],
        )

    async def test_repair_accepts_muse_fixed_question_wrapper(self) -> None:
        from backend.generation.question_library import judging

        model_result = {
            "patch": "targeted repair",
            "fixed_question": {
                "stem": "Repaired boundary question",
                "answer": "Repaired answer",
                "analysis": "Repaired analysis",
                "intuition_packet": {"practice_goal": "structural_intuition"},
            },
        }
        with (
            patch.object(judging, "is_llm_configured", return_value=True),
            patch.object(
                judging,
                "_chat_json_with_reasoning",
                new=AsyncMock(return_value=json.dumps(model_result)),
            ),
        ):
            repaired = await judging.refine_draft(
                {"stem": "Old", "answer": "Old", "analysis": "Old"},
                {"issues": ["transfer_invalid"]},
                source_pack={
                    "subject": "High school mathematics",
                    "topic": "parameter boundary",
                    "intuition_practice": {"practice_goal": "structural_intuition"},
                },
            )

        self.assertEqual(repaired["stem"], "Repaired boundary question")
        self.assertEqual(repaired["answer"], "Repaired answer")
        self.assertEqual(repaired["analysis"], "Repaired analysis")

    async def test_low_confidence_arbitration_is_isolated_and_cannot_override_hard_gate(self) -> None:
        from backend.generation.question_library import judging

        primary = {
            "pass": False,
            "confidence": 0.6,
            "dimensions": [{"name": "correctness", "score": 6, "evidence": ["x"]}],
            "issues": ["structural_depth_insufficient"],
            "deterministic_conflict": True,
            "deterministic_flags": {"structural_depth": False, "request_aligned": True},
            "deterministic_failures": ["routine_mother_question"],
        }
        arbiter = {
            **{name: True for name in judging._SUPERVISION_FLAGS},
            "pass": True,
            "confidence": 0.95,
            "dimensions": [],
            "evidence": [],
            "issues": [],
            "recommended_mutation": {},
        }
        with (
            patch.object(judging, "quick_validate_draft", new=AsyncMock(return_value=primary)),
            patch.object(judging, "_arbitrate_draft", new=AsyncMock(return_value=arbiter)) as arbitrate,
        ):
            result = await judging.supervise_draft(
                {"stem": "题干", "answer": "答案", "analysis": "解析"},
                {"subject": "高中数学", "topic": "函数"},
                source_pack={"subject": "高中数学", "topic": "函数"},
                supervision_mode="tiered_consensus",
                confidence_threshold=0.75,
            )

        self.assertTrue(result["arbitrated"])
        self.assertFalse(result["structural_depth"])
        self.assertFalse(result["pass"])
        self.assertIn("routine_mother_question", result["issues"])
        self.assertNotIn("primary", arbitrate.await_args.kwargs)

    async def test_supervisor_keeps_only_grounded_evidence(self) -> None:
        from backend.generation.question_library import judging

        draft = {
            "stem": "已知函数在区间端点取值相等，判断中点附近的变化。",
            "answer": "结论成立。",
            "analysis": "由端点条件与单调性可得结论成立。",
            "intuition_packet": {"practice_goal": "structural_intuition"},
        }
        model_payload = {
            **{name: True for name in judging._SUPERVISION_FLAGS},
            "pass": True,
            "confidence": 0.86,
            "dimensions": [
                {
                    "name": "conditions",
                    "score": 8,
                    "evidence": ["区间端点取值相等", "不存在于题目中的证据"],
                }
            ],
            "issue_codes": [],
            "issues": [],
            "recommended_mutation": {"target": "boundary", "action": "强化边界对比"},
        }
        with (
            patch.object(judging, "is_llm_configured", return_value=True),
            patch.object(
                judging,
                "_chat_json_with_reasoning",
                new=AsyncMock(return_value=json.dumps(model_payload, ensure_ascii=False)),
            ),
            patch.object(judging, "_mother_question_structural_depth", return_value=(True, [])),
            patch.object(judging, "_request_contract_alignment", return_value=(True, [])),
        ):
            result = await judging.quick_validate_draft(
                draft,
                {"subject": "高中数学", "topic": "函数"},
                source_pack={
                    "subject": "高中数学",
                    "topic": "函数",
                    "intuition_practice": {"practice_goal": "structural_intuition"},
                },
            )

        self.assertTrue(result["pass"])
        self.assertEqual(result["confidence"], 0.86)
        self.assertEqual(result["evidence"], [{"dimension": "conditions", "excerpt": "区间端点取值相等"}])


class SupervisionBenchmarkHarnessTests(unittest.TestCase):
    def test_injects_all_required_defect_families_and_scores_acceptance_gates(self) -> None:
        from backend.evals.question_generation.supervision_benchmark import (
            inject_defect_variants,
            score_supervision_benchmark,
        )

        variants = inject_defect_variants(
            {
                "stem": "已知函数满足条件一，且在区间上单调，求结论。",
                "answer": "结论成立",
                "analysis": "由条件得 \\(x\\le 1\\)，故成立。",
                "intuition_packet": {
                    "stages": [{"stage": "transfer", "prompt": "改变边界后判断"}]
                },
            }
        )
        self.assertEqual(
            {item["defect"] for item in variants},
            {
                "wrong_answer",
                "missing_condition",
                "symbol_reversal",
                "method_leak",
                "pseudo_transfer",
                "redundant_condition",
                "number_only_copy",
            },
        )
        rows = [
            {
                "defect": "good",
                "score": 95,
                "pass": True,
                "evidence": ["grounded"],
                "fitness_counted": True,
            }
        ]
        rows.extend(
            {
                "defect": item["defect"],
                "expected_issue_code": item["expected_issue_code"],
                "predicted_issue_codes": [item["expected_issue_code"]],
                "score": 20,
                "pass": False,
                "evidence": ["grounded"],
                "fitness_counted": True,
            }
            for item in variants
        )
        metrics = score_supervision_benchmark(rows)
        self.assertTrue(metrics["passed"])
        self.assertEqual(metrics["fatal_defect_recall"], 1.0)
        self.assertEqual(metrics["false_allow_rate"], 0.0)
        self.assertEqual(metrics["ranking_accuracy"], 1.0)
        self.assertEqual(metrics["unsupported_fitness_labels"], 0)
