import json
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.repositories.question import question_cache as cache_repo
from backend.database.repositories.question import question_library as lib_repo
from backend.database.schema import Base


class TestQuestionLibraryWorkerOnce(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.patches = [
            patch.object(cache_repo, "async_session_maker", self.session_maker),
            patch.object(lib_repo, "async_session_maker", self.session_maker),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_score_batch_once_hides_low_score(self) -> None:
        await cache_repo.upsert_question_cache([{"question_id": "q1", "subject": "高中数学", "stem": "stem 1"}])
        await lib_repo.upsert_question_library_items(
            user_id="u1",
            items=[{"question_id": "q1", "subject": "高中数学", "origin": "crawled"}],
        )

        fake = json.dumps(
            {
                "verdict": "差题",
                "overall_score": 60,
                "dimensions": [],
                "highlights": [],
                "issues": [],
                "summary": "bad",
            },
            ensure_ascii=False,
        )

        from backend.question_library.worker import score_batch_once

        with patch("backend.question_library.scoring.chat_completion_text", new=AsyncMock(return_value=fake)):
            n = await score_batch_once(user_id="u1", subject="高中数学", model="dummy", threshold=70, limit=10)
        self.assertEqual(n, 1)

        hidden_list = await lib_repo.list_question_library_items(user_id="u1", subject="高中数学", hidden="1", limit=10)
        self.assertEqual(len(hidden_list["items"]), 1)
