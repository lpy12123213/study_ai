import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class TestZujuanExportBehavior(unittest.IsolatedAsyncioTestCase):
    def test_diagnose_export_resolves_repo_root_env_file(self) -> None:
        import backend.mcp.core.diagnostics as diagnostics

        with patch.object(diagnostics, "__file__", r"C:\repo\backend\mcp\core\diagnostics.py"):
            resolved = diagnostics.resolve_repo_env_file()

        self.assertEqual(str(resolved), r"C:\repo\.env")

    def test_build_curl_cmd_prefers_crawler_cookie_over_env_cookie(self) -> None:
        from backend.crawler.zujuan.formulas import build_curl_cmd

        crawler = SimpleNamespace(
            user_agent="UA",
            cookies="aliyungf_tc=anti-bot; userId=123; bankId=15",
        )

        with patch(
            "backend.crawler.zujuan.formulas.load_env_login",
            return_value={"is_logged_in": True, "cookies": "userId=123; bankId=15"},
        ):
            cmd = build_curl_cmd(crawler, "https://zujuan.xkw.com/15q1.html", use_login_cookie=True)

        joined = " ".join(cmd)
        self.assertIn("Cookie: aliyungf_tc=anti-bot; userId=123; bankId=15", joined)

    async def test_export_to_basket_uses_subject_question_type_id_map(self) -> None:
        from backend.crawler.zujuan.basket import export_to_basket

        captured: dict = {}

        class FakeResponse:
            status_code = 200
            text = json.dumps({"questions": [{"questionId": 1}]}, ensure_ascii=False)

            def json(self):  # type: ignore[no-untyped-def]
                return json.loads(self.text)

        class FakeClient:
            def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                _ = args, kwargs

            async def __aenter__(self):  # type: ignore[no-untyped-def]
                return self

            async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
                _ = exc_type, exc, tb
                return False

            async def post(self, url, data=None, headers=None):  # type: ignore[no-untyped-def]
                captured["url"] = url
                captured["data"] = data
                captured["headers"] = headers
                return FakeResponse()

        crawler = SimpleNamespace(
            bank_id=15,
            subject="高中生物",
            base_url="https://zujuan.xkw.com",
            user_agent="UA",
            ques_type_map={"解答题": 3106},
            get_available_filters=AsyncMock(
                return_value={
                    "success": True,
                    "question_types": [{"id": 3106, "name": "解答题"}],
                }
            ),
            _question_type_code=lambda question_type: 3106 if question_type == "解答题" else 0,
        )

        with patch(
            "backend.crawler.zujuan.basket.get_login_session_with_playwright",
            new=AsyncMock(
                return_value={
                    "is_logged_in": True,
                    "cookies": "userId=123; bankId=15",
                    "csrf_token": "csrf-token",
                }
            ),
        ), patch("backend.crawler.zujuan.basket.httpx.AsyncClient", FakeClient):
            result = await export_to_basket(
                crawler,
                question_ids=["1"],
                question_details=[{"question_id": "1", "type": "解答题", "difficulty": "中等"}],
                auto_login=False,
            )

        self.assertTrue(result["success"])
        basket_items = json.loads(captured["data"]["basketJson"])
        self.assertEqual(basket_items[0]["quesTypeId"], 3106)

    async def test_export_to_basket_marks_dynamic_select_types(self) -> None:
        from backend.crawler.zujuan.basket import export_to_basket

        captured: dict = {}

        class FakeResponse:
            status_code = 200
            text = json.dumps({"questions": [{"questionId": 1}]}, ensure_ascii=False)

            def json(self):  # type: ignore[no-untyped-def]
                return json.loads(self.text)

        class FakeClient:
            def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                _ = args, kwargs

            async def __aenter__(self):  # type: ignore[no-untyped-def]
                return self

            async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
                _ = exc_type, exc, tb
                return False

            async def post(self, url, data=None, headers=None):  # type: ignore[no-untyped-def]
                captured["url"] = url
                captured["data"] = data
                captured["headers"] = headers
                return FakeResponse()

        crawler = SimpleNamespace(
            bank_id=15,
            subject="高中生物",
            base_url="https://zujuan.xkw.com",
            user_agent="UA",
            ques_type_map={"单选题": 3101},
            get_available_filters=AsyncMock(
                return_value={
                    "success": True,
                    "question_types": [{"id": 3101, "name": "单选题"}],
                }
            ),
        )

        with patch(
            "backend.crawler.zujuan.basket.get_login_session_with_playwright",
            new=AsyncMock(
                return_value={
                    "is_logged_in": True,
                    "cookies": "userId=123; bankId=15",
                    "csrf_token": "csrf-token",
                }
            ),
        ), patch("backend.crawler.zujuan.basket.httpx.AsyncClient", FakeClient):
            result = await export_to_basket(
                crawler,
                question_ids=["1"],
                question_details=[{"question_id": "1", "type": "单选题-1个小题", "difficulty": "中等"}],
                auto_login=False,
            )

        self.assertTrue(result["success"])
        basket_items = json.loads(captured["data"]["basketJson"])
        self.assertEqual(basket_items[0]["quesTypeId"], 3101)
        self.assertTrue(basket_items[0]["ext"]["isSelectType"])

    async def test_resolve_question_type_ids_prefers_current_subject_filters(self) -> None:
        from backend.crawler.zujuan.basket import _resolve_question_type_ids

        crawler = SimpleNamespace(
            ques_type_map={"解答题": 5104, "单选题": 1200401},
            get_available_filters=AsyncMock(
                return_value={
                    "success": True,
                    "question_types": [
                        {"id": 3101, "name": "单选题"},
                        {"id": 3103, "name": "多选题"},
                        {"id": 3106, "name": "解答题"},
                    ],
                }
            ),
        )

        resolved = await _resolve_question_type_ids(crawler)

        self.assertEqual(resolved["解答题"], 3106)
        self.assertEqual(resolved["单选题"], 3101)

    def test_resolve_export_question_type_id_normalizes_composite_type_names(self) -> None:
        from backend.crawler.zujuan.basket import _resolve_export_question_type_id

        type_map = {
            "单选题": 3101,
            "多选题": 3103,
            "解答题": 3106,
            "实验题": 3107,
        }

        self.assertEqual(_resolve_export_question_type_id("单选题-1个小题", type_map), 3101)
        self.assertEqual(_resolve_export_question_type_id("多选题-3个答案", type_map), 3103)
        self.assertEqual(_resolve_export_question_type_id("解答题", type_map), 3106)

    def test_is_select_question_type_supports_dynamic_subject_ids(self) -> None:
        from backend.crawler.zujuan.basket import _is_select_question_type

        type_map = {
            "单选题": 3101,
            "多选题": 3103,
            "解答题": 3106,
        }

        self.assertTrue(_is_select_question_type("单选题-1个小题", 3101, type_map))
        self.assertTrue(_is_select_question_type("多选题", 3103, type_map))
        self.assertFalse(_is_select_question_type("解答题", 3106, type_map))


if __name__ == "__main__":
    unittest.main()
