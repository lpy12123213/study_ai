import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.api.auth import require_auth
from backend.app import create_app


class TestQuestionLibraryMediaImport(unittest.TestCase):
    def test_normalize_extracted_questions_accepts_chinese_keys_and_caps_count(self) -> None:
        from backend.generation.question_library.media_import import normalize_extracted_questions

        payload = {
            "questions": [
                {"题干": "题干 A", "答案": "答案 A", "解析": ["步骤 1", "步骤 2"]},
                {"stem": "题干 B", "answer": "答案 B", "analysis": "解析 B"},
                {"stem": "   "},
            ]
        }

        out = normalize_extracted_questions(payload, max_questions=1)

        self.assertEqual(out, [{"stem": "题干 A", "answer": "答案 A", "analysis": "步骤 1\n步骤 2"}])

    def test_build_media_import_messages_attaches_all_images(self) -> None:
        from backend.generation.question_library.media_import import ImagePage, build_media_import_messages

        pages = [
            ImagePage(source_filename="a.png", page_number=1, mime="image/png", data=b"png-a"),
            ImagePage(source_filename="b.jpg", page_number=1, mime="image/jpeg", data=b"jpg-b"),
        ]

        messages = build_media_import_messages(
            subject="高中数学",
            topic="函数",
            difficulty="中等",
            question_type="选择题",
            max_questions=2,
            pages=pages,
        )

        self.assertEqual(messages[0]["role"], "system")
        user_content = messages[1]["content"]
        self.assertIsInstance(user_content, list)
        image_blocks = [
            block for block in user_content if isinstance(block, dict) and block.get("type") == "image_url"
        ]
        self.assertEqual(len(image_blocks), 2)
        self.assertTrue(str(image_blocks[0]["image_url"]["url"]).startswith("data:image/png;base64,"))
        self.assertTrue(str(image_blocks[1]["image_url"]["url"]).startswith("data:image/jpeg;base64,"))

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF is not installed")
    def test_load_pdf_as_image_pages_renders_each_page(self) -> None:
        import fitz

        from backend.generation.question_library.media_import import MediaFileRef, load_media_as_image_pages

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "sample.pdf"
            doc = fitz.open()
            for idx in range(2):
                page = doc.new_page(width=240, height=160)
                page.insert_text((24, 40), f"Question {idx + 1}")
            doc.save(pdf_path)
            doc.close()

            pages = load_media_as_image_pages(
                MediaFileRef(path=pdf_path, filename="sample.pdf", content_type="application/pdf"),
                max_pdf_pages=5,
            )

        self.assertEqual(len(pages), 2)
        self.assertEqual([page.page_number for page in pages], [1, 2])
        self.assertTrue(all(page.mime == "image/png" for page in pages))
        self.assertTrue(all(page.data.startswith(b"\x89PNG") for page in pages))

    def test_tasks_import_media_endpoint_accepts_image_and_pdf_uploads(self) -> None:
        app = create_app()
        app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}
        task_id = "test-media-import-endpoint"
        upload_dir = Path(__file__).resolve().parents[2] / ".local" / "question_library" / "media_imports" / task_id

        async def fake_create_task(*, user_id: str, request: dict):  # type: ignore[no-untyped-def]
            self.assertEqual(user_id, "u-1")
            self.assertEqual(request["subject"], "高中数学")
            self.assertEqual(request["topic"], "函数")
            self.assertEqual(len(request["files"]), 2)
            self.assertEqual([item["content_type"] for item in request["files"]], ["image/png", "application/pdf"])
            return SimpleNamespace(task_id=task_id)

        try:
            with patch(
                "backend.generation.question_library.runner.create_media_import_task",
                new=AsyncMock(side_effect=fake_create_task),
            ):
                client = TestClient(app)
                resp = client.post(
                    "/api/tasks/question-library/import-media",
                    data={
                        "subject": "高中数学",
                        "topic": "函数",
                        "count": "3",
                        "task_id": task_id,
                    },
                    files=[
                        ("files", ("question.png", b"\x89PNG\r\n\x1a\n", "image/png")),
                        ("files", ("paper.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")),
                    ],
                )
        finally:
            app.dependency_overrides.clear()
            shutil.rmtree(upload_dir, ignore_errors=True)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"success": True, "taskId": task_id})
