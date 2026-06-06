from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.api.auth import require_auth
from backend.app import create_app
from backend.shared.tasks.runtime import RuntimeTask


class PaperExportBundleTests(unittest.IsolatedAsyncioTestCase):
    async def test_markdown_bundle_exports_exam_and_answer_key(self) -> None:
        from backend.generation.paper_compose.export import export_paper_bundle

        published_texts: list[str] = []

        async def fake_publish_generated_text(text: str, **kwargs):
            published_texts.append(text)
            idx = len(published_texts)
            return {"url": f"/api/media/generated/export-{idx}.md", "filename": f"export-{idx}.md"}

        paper = {
            "paper_id": 7,
            "paper_name": "混合卷",
            "questions": [
                {
                    "order": 1,
                    "question_id": "ai-q1",
                    "type": "解答题",
                    "stem": "已知函数 f(x)=x^2，求 f'(x)。",
                    "answer": "2x",
                    "analysis": "幂函数求导。",
                }
            ],
        }

        with (
            patch("backend.generation.paper_compose.export.get_question_cache", new=AsyncMock(return_value={})),
            patch("backend.generation.paper_compose.export.publish_generated_text", new=fake_publish_generated_text),
        ):
            out = await export_paper_bundle(paper, user_id="u-1", fmt="markdown")

        self.assertTrue(out["success"])
        self.assertTrue(out["splitBundle"])
        self.assertEqual(out["examPaperUrl"], "/api/media/generated/export-1.md")
        self.assertEqual(out["answerKeyUrl"], "/api/media/generated/export-2.md")
        self.assertEqual(len(published_texts), 2)
        self.assertIn("**题干：**", published_texts[0])
        self.assertNotIn("**答案：**", published_texts[0])
        self.assertNotIn("**解析：**", published_texts[0])
        self.assertIn("**答案：**", published_texts[1])
        self.assertIn("**解析：**", published_texts[1])


class PaperExportBundleApiTests(unittest.TestCase):
    def _override_auth(self, app) -> None:
        app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}

    def test_sync_export_endpoint_supports_split_bundle(self) -> None:
        app = create_app()
        self._override_auth(app)
        client = TestClient(app)

        export_bundle = AsyncMock(
            return_value={
                "format": "markdown",
                "success": True,
                "splitBundle": True,
                "examPaperUrl": "/exam.md",
                "answerKeyUrl": "/answer.md",
            }
        )

        with (
            patch("backend.api.papers.get_paper", new=AsyncMock(return_value={"paper_id": 1, "questions": []})),
            patch("backend.api.papers.export_paper_bundle", new=export_bundle),
        ):
            resp = client.post("/api/papers/1/export", json={"format": "markdown", "splitBundle": True})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["examPaperUrl"], "/exam.md")
        self.assertEqual(resp.json()["answerKeyUrl"], "/answer.md")
        export_bundle.assert_awaited_once()
        self.assertTrue(export_bundle.await_args.kwargs["split_bundle"])
        app.dependency_overrides.clear()


class PaperExportBundleTaskRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_export_task_uses_bundle_when_requested(self) -> None:
        from backend.tasks import runners

        class FakeTaskRuntime:
            def __init__(self) -> None:
                self.events: list[dict] = []
                self.result: dict | None = None

            async def append_event(self, task, event: dict) -> None:
                self.events.append(event)

            async def complete_task(self, task, *, result: dict | None = None) -> None:
                self.result = dict(result or {})
                task.status = "completed"

            async def fail_task(self, task, message: str, **kwargs) -> None:
                raise AssertionError(f"unexpected task failure: {message}")

        fake_runtime = FakeTaskRuntime()
        task = RuntimeTask(
            task_id="export-1",
            user_id="u-1",
            task_type="export_paper",
            title="Export",
            request={"paper_id": 1, "format": "markdown", "splitBundle": True},
        )

        export_bundle = AsyncMock(
            return_value={
                "format": "markdown",
                "success": True,
                "splitBundle": True,
                "examPaperUrl": "/exam.md",
                "answerKeyUrl": "/answer.md",
            }
        )

        with (
            patch.object(runners, "task_runtime", fake_runtime),
            patch.object(runners, "db_get_paper", new=AsyncMock(return_value={"paper_id": 1, "questions": []})),
            patch.object(runners, "export_paper_bundle", new=export_bundle),
        ):
            await runners.run_export_paper_task(task, user_id="u-1")

        self.assertEqual(task.status, "completed")
        self.assertEqual(fake_runtime.result["examPaperUrl"], "/exam.md")
        export_bundle.assert_awaited_once()
        self.assertTrue(export_bundle.await_args.kwargs["split_bundle"])


if __name__ == "__main__":
    unittest.main()
