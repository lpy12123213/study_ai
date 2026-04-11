from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.api import canvas as canvas_api
from backend.api import media as media_api
from backend.api import papers as papers_api
from backend.api import subjects as subjects_api
from backend.database.repositories.question import papers as papers_repo
from backend.database.schema import Base
from backend.study_materials import orchestrator as task_manager


class TestMediaProxyCache(unittest.IsolatedAsyncioTestCase):
    async def test_proxy_rejects_svg_payloads(self) -> None:
        class FakeResponse:
            def __init__(self) -> None:
                self.status_code = 200
                self.headers = {"content-type": "image/svg+xml"}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def aiter_bytes(self):
                if False:
                    yield b""

        class FakeClient:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, method: str, url: str):
                return FakeResponse()

        async def fake_resolve(_host: str):
            return [ipaddress.ip_address("93.184.216.34")]

        with patch.dict(os.environ, {"MEDIA_PROXY_ALLOWED_DOMAINS": "example.com"}):
            with patch("backend.api.media._resolve_host_ips", new=fake_resolve):
                with patch("backend.api.media.httpx.AsyncClient", new=FakeClient):
                    with self.assertRaises(HTTPException) as cm:
                        await media_api.proxy_media("https://example.com/test.svg")

        self.assertEqual(cm.exception.status_code, 415)
        self.assertEqual(cm.exception.detail, "svg_not_allowed")

    def test_prune_proxy_cache_enforces_ttl_and_lru_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            expired = cache_dir / "expired.png"
            old = cache_dir / "old.png"
            fresh = cache_dir / "fresh.png"

            expired.write_bytes(b"a" * 300)
            old.write_bytes(b"b" * 300)
            fresh.write_bytes(b"c" * 300)

            now = time.time()
            os.utime(expired, (now - 3600, now - 3600))
            os.utime(old, (now - 30, now - 30))
            os.utime(fresh, (now, now))

            with patch.object(media_api, "MEDIA_DIR", cache_dir):
                with patch.dict(
                    os.environ,
                    {
                        "MEDIA_PROXY_CACHE_TTL_SECONDS": "60",
                        "MEDIA_PROXY_CACHE_MAX_BYTES": "450",
                        "MEDIA_PROXY_CACHE_MAX_FILES": "10",
                    },
                ):
                    stats = media_api._prune_proxy_cache()

            self.assertFalse(expired.exists())
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
            self.assertEqual(stats["expired"], 1)
            self.assertEqual(stats["evicted_files"], 1)
            self.assertGreaterEqual(stats["evicted_bytes"], 300)


class TestStudyMaterialsTaskSnapshots(unittest.TestCase):
    def test_restore_tasks_from_disk_deletes_expired_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir)
            expired_path = snapshot_dir / "expired.json"
            fresh_path = snapshot_dir / "fresh.json"

            expired_payload = {
                "task_id": "expired-task",
                "query": "old",
                "user_id": "u1",
                "created_at_s": time.time() - 7200,
                "updated_at_s": time.time() - 7200,
                "status": "completed",
                "events": [],
                "last_seq": 0,
                "seq_offset": 0,
            }
            fresh_payload = {
                "task_id": "fresh-task",
                "query": "new",
                "user_id": "u1",
                "created_at_s": time.time(),
                "updated_at_s": time.time(),
                "status": "completed",
                "events": [],
                "last_seq": 0,
                "seq_offset": 0,
            }

            expired_path.write_text(json.dumps(expired_payload), encoding="utf-8")
            fresh_path.write_text(json.dumps(fresh_payload), encoding="utf-8")

            with patch.object(task_manager, "_TASK_SNAPSHOTS_DIR", snapshot_dir):
                manager = task_manager.StudyMaterialsTaskManager(task_ttl_s=60)
                asyncio.run(manager.restore_tasks_from_disk())

            self.assertFalse(expired_path.exists())
            self.assertTrue(fresh_path.exists())


class TestCanvasSnapshotLimits(unittest.TestCase):
    def test_serialize_snapshot_rejects_oversized_payload(self) -> None:
        payload = {"nodes": ["x" * 300] * 10}
        with patch.dict(os.environ, {"CANVAS_SNAPSHOT_MAX_BYTES": "256"}):
            with self.assertRaises(HTTPException) as cm:
                canvas_api._serialize_snapshot(payload)

        self.assertEqual(cm.exception.status_code, 413)
        self.assertEqual(cm.exception.detail, "snapshot_too_large")


class TestPaperAnalysisCaching(unittest.IsolatedAsyncioTestCase):
    async def test_get_paper_info_skips_analysis_when_not_requested(self) -> None:
        paper_payload = {
            "paper_id": 1,
            "paper_name": "Demo",
            "created_at": "2026-03-06T00:00:00",
            "updated_at": "2026-03-06T00:00:00",
            "questions": [],
        }
        with patch("backend.api.papers.get_paper", new=AsyncMock(return_value=paper_payload.copy())):
            with patch("backend.api.papers.analyze_paper", side_effect=AssertionError("should_not_run")):
                result = await papers_api.get_paper_info(1, include_analysis=False, user={"user_id": "u1"})

        self.assertNotIn("analysis", result)

    async def test_get_paper_info_caches_analysis_by_version(self) -> None:
        papers_api.clear_paper_analysis_cache()
        paper_payload = {
            "paper_id": 1,
            "paper_name": "Demo",
            "created_at": "2026-03-06T00:00:00",
            "updated_at": "2026-03-06T12:00:00",
            "questions": [{"question_id": "q1"}],
        }
        analyze = Mock(return_value={"difficulty_score": 0.5, "radar_data": [], "ai_comment": "ok"})

        with patch("backend.api.papers.get_paper", new=AsyncMock(return_value=paper_payload.copy())):
            with patch("backend.api.papers.analyze_paper", new=analyze):
                result_a = await papers_api.get_paper_info(1, include_analysis=True, user={"user_id": "u1"})
                result_b = await papers_api.get_paper_info(1, include_analysis=True, user={"user_id": "u1"})

        self.assertEqual(analyze.call_count, 1)
        self.assertEqual(result_a["analysis"]["ai_comment"], "ok")
        self.assertEqual(result_b["analysis"]["ai_comment"], "ok")


class TestSubjectFiltersCaching(unittest.IsolatedAsyncioTestCase):
    async def test_subject_filters_cache_reuses_recent_result(self) -> None:
        subjects_api.clear_subject_filters_cache()
        crawler = SimpleNamespace(
            get_available_filters=AsyncMock(
                return_value={
                    "success": True,
                    "grades": [{"id": 1, "name": "高一"}],
                    "textbook_versions": [],
                    "provinces": [],
                    "question_types": [],
                    "paper_types_by_grade": {},
                }
            )
        )

        with patch.dict(os.environ, {"SUBJECT_FILTERS_CACHE_TTL_S": "600"}):
            with patch("backend.api.subjects.resolve_subject", return_value="高中数学"):
                with patch("backend.api.subjects.get_crawler", new=AsyncMock(return_value=crawler)):
                    first = await subjects_api.get_subject_filters("高中数学", user={"user_id": "u1"})
                    second = await subjects_api.get_subject_filters("高中数学", user={"user_id": "u1"})

        self.assertEqual(crawler.get_available_filters.await_count, 1)
        self.assertEqual(first["grades"], second["grades"])


class TestPaperContentStorageConfig(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.patches = [patch.object(papers_repo, "async_session_maker", self.session_maker)]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_save_paper_omits_question_content_by_default(self) -> None:
        paper_id = await papers_repo.save_paper(
            user_id="user-a",
            paper_name="Compliance",
            questions=[
                {
                    "question_id": "q-1",
                    "stem": "题干内容",
                    "answer": "答案",
                    "analysis": "解析",
                }
            ],
        )

        stored = await papers_repo.get_paper(user_id="user-a", paper_id=paper_id)
        question = stored["questions"][0]
        self.assertEqual(question["stem"], "")
        self.assertEqual(question["answer"], "")
        self.assertEqual(question["analysis"], "")

    async def test_save_paper_can_opt_in_question_content_storage(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PAPER_STORE_STEM": "true",
                "PAPER_STORE_ANSWER": "true",
                "PAPER_STORE_ANALYSIS": "true",
            },
        ):
            paper_id = await papers_repo.save_paper(
                user_id="user-a",
                paper_name="Teacher Copy",
                questions=[
                    {
                        "question_id": "q-2",
                        "stem": "题干内容",
                        "answer": "答案",
                        "analysis": "解析",
                    }
                ],
            )

        stored = await papers_repo.get_paper(user_id="user-a", paper_id=paper_id)
        question = stored["questions"][0]
        self.assertEqual(question["stem"], "题干内容")
        self.assertEqual(question["answer"], "答案")
        self.assertEqual(question["analysis"], "解析")
