from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.api.auth import require_admin
from backend.api.auth_schemas import RegisterRequest
from backend.api.middleware.input_validation import InputValidationMiddleware
from backend.api.middleware.rate_limit import register_rate_limit_middleware
from backend.api.middleware.security_headers import register_security_headers_middleware
from backend.core import auth as core_auth
from backend.database.repositories.exam import exam_sessions as exam_repo
from backend.database.repositories.question import papers as papers_repo
from backend.database.schema import Base
from backend.generation.exam_grading.orchestrator import grade_exam_session
from backend.generation.exam_grading.subjective import grade_subjective_answer
from backend.integrations.crawler.zujuan import formulas
from backend.integrations.crawler.zujuan.basket import export_to_basket, login_via_subprocess
from backend.integrations.crawler.zujuan.client import ZujuanCrawler
from backend.llm import metrics as llm_metrics
from backend.llm.streaming import read_stream_response
from backend.llm.transport import client_post


class AuthSecurityRegressionTests(unittest.TestCase):
    def test_validate_access_token_rejects_missing_jti(self) -> None:
        with (
            patch.object(
                core_auth,
                "decode_token",
                return_value={"user_id": "u1", "username": "alice", "ver": 1},
            ),
            patch.object(
                core_auth._user_repo,
                "get_user_by_username",
                return_value={"user_id": "u1", "username": "alice", "token_version": 1},
            ),
        ):
            self.assertIsNone(core_auth.validate_access_token("token-without-jti"))

    def test_legacy_sha256_verify_uses_constant_time_compare(self) -> None:
        legacy = core_auth._legacy_sha256("secret")
        with patch.object(core_auth.hmac, "compare_digest", wraps=core_auth.hmac.compare_digest) as compare_digest:
            self.assertTrue(core_auth.verify_password("secret", legacy))
        compare_digest.assert_called_once()

    def test_register_role_is_limited_to_known_values(self) -> None:
        with self.assertRaises(ValueError):
            RegisterRequest(username="alice", password="secret1", role="owner")

    def test_require_admin_rejects_local_fallback_user(self) -> None:
        with self.assertRaises(Exception) as ctx:
            asyncio.run(require_admin({"user_id": "local-user", "username": "本地用户", "role": "admin"}))
        self.assertEqual(getattr(ctx.exception, "status_code", None), 403)


class MiddlewareSecurityRegressionTests(unittest.TestCase):
    def test_input_validation_rechecks_dangerous_protocol_after_tag_strip(self) -> None:
        middleware = InputValidationMiddleware(app=lambda scope, receive, send: None)
        with self.assertRaises(ValueError):
            middleware._sanitize_str("java<b>script:alert(1)")

    def test_login_path_uses_auth_failure_limiter(self) -> None:
        app = FastAPI()

        @app.post("/api/auth/login")
        def login() -> JSONResponse:
            return JSONResponse({"detail": "bad"}, status_code=401)

        env = {
            "API_RATE_LIMIT_MAX_REQUESTS": "100",
            "API_RATE_LIMIT_WINDOW_S": "60",
            "API_RATE_LIMIT_MAX_KEYS": "100",
            "AUTH_RATE_LIMIT_MAX_FAILS": "1",
            "AUTH_RATE_LIMIT_WINDOW_S": "60",
        }
        with patch.dict(os.environ, env, clear=False):
            register_rate_limit_middleware(app, client_ip=lambda request: "127.0.0.1")
        client = TestClient(app)

        self.assertEqual(client.post("/api/auth/login").status_code, 401)
        self.assertEqual(client.post("/api/auth/login").status_code, 429)

    def test_security_headers_include_csp_and_https_hsts(self) -> None:
        app = FastAPI()
        register_security_headers_middleware(app)

        @app.get("/api/ping")
        def ping() -> dict[str, str]:
            return {"ok": "1"}

        res = TestClient(app, base_url="https://testserver").get("/api/ping")

        self.assertTrue(res.headers.get("Content-Security-Policy"))
        self.assertTrue(res.headers.get("Strict-Transport-Security"))
        self.assertEqual(res.headers.get("Cross-Origin-Resource-Policy"), "same-origin")


class ExamIntegrityRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.patches = [
            patch.object(papers_repo, "async_session_maker", self.session_maker),
            patch.object(exam_repo, "async_session_maker", self.session_maker),
        ]
        for item in self.patches:
            item.start()
        self.paper_id = await papers_repo.save_paper(
            user_id="user-a",
            paper_name="edge",
            questions=[
                {"question_id": "q1", "type": "single_choice", "stem": "x", "answer": "A", "points": 0.5},
            ],
        )

    async def asyncTearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_submit_session_rejects_terminal_session_resubmit(self) -> None:
        created = await exam_repo.create_exam_session(user_id="user-a", paper_id=self.paper_id, mode="untimed")
        await exam_repo.submit_session(user_id="user-a", session_id=created["session_id"], total_score=0.5, max_score=0.5)

        with self.assertRaisesRegex(ValueError, "session_not_in_progress"):
            await exam_repo.submit_session(
                user_id="user-a",
                session_id=created["session_id"],
                total_score=0.0,
                max_score=0.5,
            )

    async def test_grade_exam_ratio_uses_real_fractional_max_score(self) -> None:
        session_payload = {
            "session_id": "s1",
            "status": "in_progress",
            "answers": [{"id": 1, "question_id": "q1", "selected_options": ["A"], "max_score": 0.5}],
            "questions": [{"question_id": "q1", "type": "single_choice", "answer": "A", "max_score": 0.5}],
        }
        with (
            patch.object(exam_repo, "get_exam_session", new=AsyncMock(return_value=session_payload)),
            patch.object(exam_repo, "update_answer_score", new=AsyncMock()),
            patch.object(exam_repo, "submit_session", new=AsyncMock()),
            patch.object(exam_repo, "create_exam_result", new=AsyncMock(side_effect=lambda **kwargs: kwargs["result_data"])),
        ):
            result = await grade_exam_session(user_id="user-a", session_id="s1")

        self.assertEqual(result["total_score"], 0.5)
        self.assertEqual(result["max_score"], 0.5)
        self.assertEqual(result["score_ratio"], 1.0)

    async def test_subjective_fallback_does_not_award_unreviewed_text(self) -> None:
        with patch("backend.generation.exam_grading.subjective.is_llm_configured", return_value=False):
            result = await grade_subjective_answer(
                question={"stem": "证明"},
                answer_data={"text_answer": "随便写几句"},
                max_score=10,
            )

        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["is_correct"], None)


class ZujuanRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_export_to_basket_rejects_non_numeric_question_id_with_structured_error(self) -> None:
        class FakeCrawler:
            subject = "高中数学"
            bank_id = 11

        with patch(
            "backend.integrations.crawler.zujuan.basket.get_login_session_with_playwright",
            new=AsyncMock(return_value={"is_logged_in": True, "cookies": "bankId=11", "csrf_token": "csrf"}),
        ):
            result = await export_to_basket(FakeCrawler(), ["bad-id"], auto_login=False)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid_question_id")

    async def test_login_via_subprocess_rejects_subject_when_subjects_module_missing(self) -> None:
        class FakeCrawler:
            subject = "math&calc"

        with patch.dict("sys.modules", {"backend.core.subjects": None}):
            result = await login_via_subprocess(FakeCrawler())

        self.assertFalse(result["success"])

    def test_client_compacts_whitespace_when_mapping_province_names(self) -> None:
        crawler = ZujuanCrawler(subject="高中数学")
        crawler._set_provinces_from_list([{"id": 42, "name": "内蒙古 自治区"}])

        self.assertEqual(crawler.province_name_to_id.get("内蒙古自治区"), 42)

    def test_parse_target_from_payload_tolerates_non_dict_data(self) -> None:
        crawler = ZujuanCrawler(subject="高中数学")

        target = crawler._parse_target_from_payload({"url": "/gzsx/zsd123", "data": None})

        self.assertEqual(target["category_id"], "123")
        self.assertEqual(target["bank_id"], 0)

    async def test_formula_replacement_uses_literal_svg_replacement(self) -> None:
        class FakeCrawler:
            base_url = "https://zujuan.test"

        with patch.object(formulas, "fetch_formula_svg", new=AsyncMock(return_value=r"<svg>\1</svg>")):
            result = await formulas.replace_formulas_with_inline_svg(
                FakeCrawler(),
                '<img src="/Upload/formula/a.png">',
            )

        self.assertIn(r"<svg>\1</svg>", result)


class LlmRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_post_preserves_unrelated_type_error(self) -> None:
        class FakeClient:
            async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
                raise TypeError("unrelated application bug")

        with self.assertRaisesRegex(TypeError, "unrelated application bug"):
            await client_post(FakeClient(), "https://example.test", headers={}, payload={}, timeout_s=3)

    def test_recent_llm_calls_includes_prompt_completion_by_model(self) -> None:
        llm_metrics.clear_llm_debug_calls()
        llm_metrics.record_llm_call(
            provider="openrouter",
            model="m",
            usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            stream=False,
            elapsed_s=0.1,
            finish_reason="stop",
            request_id="req",
        )

        bucket = llm_metrics.recent_llm_calls()["by_model"]["openrouter:m"]

        self.assertEqual(bucket["prompt_tokens"], 2)
        self.assertEqual(bucket["completion_tokens"], 3)

    async def test_streaming_usage_merges_partial_usage_chunks(self) -> None:
        class FakeResponse:
            async def aiter_lines(self):
                yield 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}'
                yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"completion_tokens":2}}'
                yield "data: [DONE]"

        result = await read_stream_response(
            resp=FakeResponse(),
            req_id="req",
            provider="openrouter",
            model="m",
            emit_chars=10,
            emit_interval_s=1,
            on_reasoning_delta=None,
            on_content_delta=None,
        )

        self.assertEqual(result.usage["prompt_tokens"], 2)
        self.assertEqual(result.usage["completion_tokens"], 2)
        self.assertEqual(result.usage["total_tokens"], 3)


if __name__ == "__main__":
    unittest.main()
