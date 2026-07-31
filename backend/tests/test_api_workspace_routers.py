"""Thin workspace routers (annotations/dashboard/feedback/share_links/templates/wrongbook) tests.

These routers are thin wrappers over the repository layer, so the tests patch
the ``db_*`` repository functions imported into each module and call the async
handlers directly — covering user_id guards, payload parsing, error mapping
(ValueError→400, repo failure→500, missing→404) and response shapes without a
database or HTTP client.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from backend.api import annotations, dashboard, feedback, share_links, templates, wrongbook

USER = {"user_id": "u-test"}


def _http_code(exc: HTTPException) -> int:
    return int(exc.status_code or 0)


class TestAnnotationsRouter(unittest.IsolatedAsyncioTestCase):
    async def test_list_returns_items_and_count(self) -> None:
        with patch.object(annotations, "db_list_annotations", new=AsyncMock(return_value=[{"id": 1}, {"id": 2}])) as m:
            out = await annotations.list_user_annotations(item_type="paper", item_id=None, tag="重点", limit=50, user=USER)
        self.assertEqual(out["count"], 2)
        self.assertEqual(len(out["annotations"]), 2)
        _, kwargs = m.await_args
        self.assertEqual(kwargs["user_id"], "u-test")
        self.assertEqual(kwargs["item_type"], "paper")
        self.assertEqual(kwargs["tag"], "重点")

    async def test_list_requires_user_id(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await annotations.list_user_annotations(item_type=None, item_id=None, tag=None, limit=10, user={})
        self.assertEqual(_http_code(ctx.exception), 401)

    async def test_create_maps_value_error_to_400(self) -> None:
        with patch.object(annotations, "db_create_annotation", new=AsyncMock(side_effect=ValueError("missing_item"))):
            with self.assertRaises(HTTPException) as ctx:
                await annotations.create_user_annotation({"item_type": "", "item_id": ""}, user=USER)
        self.assertEqual(_http_code(ctx.exception), 400)

    async def test_update_not_found_is_404(self) -> None:
        with patch.object(annotations, "db_update_annotation", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await annotations.update_user_annotation(42, {"content": "x"}, user=USER)
        self.assertEqual(_http_code(ctx.exception), 404)


class TestFeedbackRouter(unittest.IsolatedAsyncioTestCase):
    async def test_create_happy_path(self) -> None:
        with patch.object(feedback, "db_create_feedback", new=AsyncMock(return_value={"id": 7})) as m:
            out = await feedback.create_user_feedback({"title": "建议", "description": "内容", "context": {"page": "chat"}}, user=USER)
        self.assertTrue(out["success"])
        self.assertEqual(out["feedback"], {"id": 7})
        _, kwargs = m.await_args
        self.assertEqual(kwargs["title"], "建议")

    async def test_create_maps_value_error_to_400(self) -> None:
        with patch.object(feedback, "db_create_feedback", new=AsyncMock(side_effect=ValueError("too_long"))):
            with self.assertRaises(HTTPException) as ctx:
                await feedback.create_user_feedback({"title": "t"}, user=USER)
        self.assertEqual(_http_code(ctx.exception), 400)

    async def test_list_requires_user_id(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await feedback.list_user_feedback(limit=10, user={})
        self.assertEqual(_http_code(ctx.exception), 401)


class TestTemplatesRouter(unittest.IsolatedAsyncioTestCase):
    async def test_update_not_found_is_404(self) -> None:
        with patch.object(templates, "db_update_template", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await templates.update_user_template(3, {"name": "n"}, user=USER)
        self.assertEqual(_http_code(ctx.exception), 404)

    async def test_delete_not_found_is_404(self) -> None:
        with patch.object(templates, "db_delete_template", new=AsyncMock(return_value=False)):
            with self.assertRaises(HTTPException) as ctx:
                await templates.delete_user_template(3, user=USER)
        self.assertEqual(_http_code(ctx.exception), 404)

    async def test_import_rejects_non_list_payload(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await templates.import_user_templates({"templates": "nope"}, user=USER)
        self.assertEqual(_http_code(ctx.exception), 400)

    async def test_import_skips_entries_without_type(self) -> None:
        with patch.object(templates, "db_create_template", new=AsyncMock(side_effect=lambda **kw: kw)) as m:
            out = await templates.import_user_templates(
                {"templates": [{"name": "无类型"}, {"template_type": "lesson", "name": "教案A"}]}, user=USER
            )
        self.assertEqual(out["count"], 1)
        self.assertEqual(m.await_count, 1)

    async def test_get_not_found_is_404(self) -> None:
        with patch.object(templates, "db_get_template", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await templates.get_user_template(9, user=USER)
        self.assertEqual(_http_code(ctx.exception), 404)


class TestWrongbookRouter(unittest.IsolatedAsyncioTestCase):
    async def test_review_rejects_invalid_rating(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await wrongbook.record_wrongbook_review("q1", {"rating": "bogus"}, user=USER)
        self.assertEqual(_http_code(ctx.exception), 400)

    async def test_review_not_found_is_404(self) -> None:
        rating = next(iter(wrongbook.RATING_QUALITY))
        with patch.object(wrongbook, "db_record_review", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await wrongbook.record_wrongbook_review("q1", {"rating": rating}, user=USER)
        self.assertEqual(_http_code(ctx.exception), 404)

    async def test_delete_not_found_is_404(self) -> None:
        with patch.object(wrongbook, "db_delete_wrong_question", new=AsyncMock(return_value=False)):
            with self.assertRaises(HTTPException) as ctx:
                await wrongbook.delete_wrongbook_item("q1", user=USER)
        self.assertEqual(_http_code(ctx.exception), 404)

    async def test_practice_requires_questions(self) -> None:
        with patch.object(wrongbook, "db_list_wrong_questions", new=AsyncMock(return_value=[])):
            with self.assertRaises(HTTPException) as ctx:
                await wrongbook.generate_practice_paper({"paper_name": "练习"}, user=USER)
        self.assertEqual(_http_code(ctx.exception), 400)

    async def test_practice_filters_selected_and_creates_paper(self) -> None:
        items = [
            {"question_id": "q1", "knowledge_point": "函数"},
            {"question_id": "q2", "knowledge_point": "导数"},
        ]
        with (
            patch.object(wrongbook, "db_list_wrong_questions", new=AsyncMock(return_value=items)),
            patch.object(wrongbook, "db_save_paper", new=AsyncMock(return_value=123)) as save,
        ):
            out = await wrongbook.generate_practice_paper({"paper_name": "练习", "question_ids": ["q2"]}, user=USER)
        self.assertTrue(out["success"])
        self.assertEqual(out["paper_id"], 123)
        _, kwargs = save.await_args
        self.assertEqual(len(kwargs["questions"]), 1)
        self.assertEqual(kwargs["questions"][0]["question_id"], "q2")


class TestShareLinksRouter(unittest.IsolatedAsyncioTestCase):
    def test_is_expired_semantics(self) -> None:
        self.assertFalse(share_links._is_expired(""))
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.assertTrue(share_links._is_expired(past))
        self.assertFalse(share_links._is_expired(future))
        # 畸形时间戳按过期处理（fail closed）
        self.assertTrue(share_links._is_expired("not-a-date"))

    async def test_create_requires_item_ref(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await share_links.create_share_link({"item_type": "paper"}, user=USER)
        self.assertEqual(_http_code(ctx.exception), 400)

    async def test_create_happy_path_returns_public_meta(self) -> None:
        link = {"token": "tok", "item_type": "paper", "expires_at": "", "created_at": "2026-01-01", "has_password": False}
        with patch.object(share_links, "db_create_share_link", new=AsyncMock(return_value=link)):
            out = await share_links.create_share_link({"item_type": "paper", "item_id": "5"}, user=USER)
        self.assertTrue(out["success"])
        self.assertEqual(out["token"], "tok")
        self.assertNotIn("user_id", out)

    async def test_public_meta_missing_is_404(self) -> None:
        with patch.object(share_links, "db_get_share_link", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await share_links.get_share_link_meta("nope")
        self.assertEqual(_http_code(ctx.exception), 404)

    async def test_public_meta_expired_is_410(self) -> None:
        expired = {"token": "t", "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}
        with patch.object(share_links, "db_get_share_link", new=AsyncMock(return_value=expired)):
            with self.assertRaises(HTTPException) as ctx:
                await share_links.get_share_link_meta("t")
        self.assertEqual(_http_code(ctx.exception), 410)

    async def test_validate_wrong_password_is_403(self) -> None:
        meta = {"token": "t", "expires_at": ""}
        with (
            patch.object(share_links, "db_validate_share_link", new=AsyncMock(return_value=None)),
            patch.object(share_links, "db_get_share_link", new=AsyncMock(return_value=meta)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await share_links.validate_share_link("t", {"password": "bad"}, request=None)
        self.assertEqual(_http_code(ctx.exception), 403)

    async def test_content_unsupported_type_is_400(self) -> None:
        link = {"token": "t", "user_id": "u", "item_type": "video", "item_id": "1"}
        with patch.object(share_links, "db_validate_share_link", new=AsyncMock(return_value=link)):
            with self.assertRaises(HTTPException) as ctx:
                await share_links.fetch_shared_content("t", {}, request=None)
        self.assertEqual(_http_code(ctx.exception), 400)

    async def test_content_paper_happy_path(self) -> None:
        link = {"token": "t", "user_id": "u", "item_type": "paper", "item_id": "5"}
        with (
            patch.object(share_links, "db_validate_share_link", new=AsyncMock(return_value=link)),
            patch.object(share_links, "db_get_paper", new=AsyncMock(return_value={"paper_id": 5})),
        ):
            out = await share_links.fetch_shared_content("t", {}, request=None)
        self.assertEqual(out["item_type"], "paper")
        self.assertEqual(out["paper"], {"paper_id": 5})


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeSession:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _stmt):
        return _FakeResult(self._results.pop(0))


class _FakeSessionCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


class TestDashboardRouter(unittest.IsolatedAsyncioTestCase):
    def test_window_defaults_to_days_before_to(self) -> None:
        dt_from, dt_to = dashboard._window(None, "2026-07-01T00:00:00Z", 30)
        self.assertEqual(dt_to, datetime(2026, 7, 1, tzinfo=timezone.utc))
        self.assertEqual(dt_from, dt_to - timedelta(days=30))

    def test_window_swaps_inverted_range(self) -> None:
        dt_from, dt_to = dashboard._window("2026-07-10T00:00:00Z", "2026-07-01T00:00:00Z", 30)
        self.assertLess(dt_from, dt_to)

    def test_extract_subject(self) -> None:
        self.assertEqual(dashboard._extract_subject({"subject": " 高中数学 "}), "高中数学")
        self.assertEqual(dashboard._extract_subject({"Subject": "物理"}), "物理")
        self.assertEqual(dashboard._extract_subject({"other": 1}), "")
        self.assertEqual(dashboard._extract_subject("not-a-dict"), "")

    async def test_stats_requires_user_id(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await dashboard.get_dashboard_stats(days=30, from_=None, to=None, user={})
        self.assertEqual(_http_code(ctx.exception), 401)

    async def test_stats_aggregates_tasks_and_exports(self) -> None:
        started = datetime(2026, 6, 20, 10, 0, 0)
        ended = datetime(2026, 6, 20, 10, 1, 0)
        tasks = [
            SimpleNamespace(
                task_id="t1",
                id=1,
                task_type="study_materials",
                status="completed",
                request_json='{"subject": "数学"}',
                started_at=started,
                ended_at=ended,
            ),
            SimpleNamespace(
                task_id="t2",
                id=2,
                task_type="study_materials",
                status="failed",
                request_json="not-json",
                started_at=None,
                ended_at=None,
            ),
        ]
        generated = [SimpleNamespace(file_type="pdf"), SimpleNamespace(file_type="docx"), SimpleNamespace(file_type="pdf")]
        session = _FakeSession([tasks, generated])
        with patch.object(dashboard, "async_session_maker", return_value=_FakeSessionCM(session)):
            out = await dashboard.get_dashboard_stats(days=60, from_=None, to=None, user=USER)

        self.assertEqual(out["tasks_total"], 2)
        self.assertEqual(out["tasks_by_type"], {"study_materials": 2})
        self.assertEqual(out["tasks_by_status"], {"completed": 1, "failed": 1})
        self.assertAlmostEqual(out["completion_rate"], 0.5)
        self.assertAlmostEqual(out["avg_duration_s"], 60.0)
        self.assertEqual(out["exports_total"], 3)
        self.assertEqual(out["exports_by_type"], {"pdf": 2, "docx": 1})
        self.assertEqual(out["top_subjects"], [{"subject": "数学", "count": 1}])


if __name__ == "__main__":
    unittest.main()
